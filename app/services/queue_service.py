import asyncio
import logging
import random
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import or_
from app.config import settings
from app.db import SessionLocal
from app.models.monitor import Monitor
from app.models.check_run import CheckRun
from app.models.version import Version
from app.models.queue_job import QueueJob
from app.models.notification import AlertEvent
from app.models.numeric_observation import NumericObservation
from app.services.browser_capture import browser_capture_service
from app.services.normalizer import compute_normalized_content, is_meaningful_change, matches_keyword_filter, parse_numeric_value
from app.services.diff_engine import generate_text_diff, generate_diff_summary, generate_visual_diff
from app.services.artifact_storage import artifact_storage
from app.services.notifier import dispatch_alert_event

logger = logging.getLogger("changewatch.queue")


def _try_save_screenshot(image_bytes: bytes, monitor_id: str, version_id: str) -> Optional[str]:
    """Persist screenshots when durable storage is configured; text monitoring must survive otherwise."""
    if not image_bytes:
        return None
    if settings.is_vercel and (
        settings.artifact_backend != "s3" or not settings.S3_BUCKET.strip()
    ):
        logger.warning(
            "Skipping screenshot for monitor %s: configure S3_BUCKET for durable screenshot history",
            monitor_id,
        )
        return None
    try:
        return artifact_storage.save_screenshot(image_bytes, monitor_id, version_id)
    except Exception:
        # Browser capture and text diffing are the core monitor function; an
        # optional screenshot-storage outage must not leave a monitor uninitialized.
        logger.exception("Could not persist screenshot for monitor %s; continuing text-only", monitor_id)
        return None


def _try_read_screenshot(filename: str) -> Optional[bytes]:
    try:
        return artifact_storage.read_bytes(filename)
    except Exception:
        logger.exception("Could not read prior screenshot artifact; skipping visual diff")
        return None


def enqueue_check(db: Session, monitor_id: str, is_manual: bool = False) -> Optional[QueueJob]:
    """
    Enqueues a monitor check job. Coalesces duplicate jobs if a check is already pending or running.
    """
    existing = db.query(QueueJob).filter(
        QueueJob.task_type == "check_monitor",
        QueueJob.status.in_(["pending", "running"]),
        QueueJob.payload_json.like(f'%"monitor_id": "{monitor_id}"%')
    ).first()

    if existing:
        return existing

    job = QueueJob(
        task_type="check_monitor",
        payload={"monitor_id": monitor_id, "is_manual": is_manual},
        status="pending",
        scheduled_at=datetime.now(timezone.utc),
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


async def _process_check_job_impl(db: Session, job: QueueJob, allow_test_fixtures: bool = False) -> bool:
    """Executes a single check_monitor queue job."""
    payload = job.payload
    monitor_id = payload.get("monitor_id")
    monitor = db.query(Monitor).filter(Monitor.id == monitor_id).first()

    if not monitor or monitor.state == "paused":
        job.status = "completed"
        job.completed_at = datetime.now(timezone.utc)
        job.locked_at = None
        job.locked_by = None
        db.commit()
        return True

    # Publish progress to the UI before spending time in browser capture.
    # Without this state, an executing first check still looks permanently Pending.
    now_started = datetime.now(timezone.utc)
    job.status = "running"
    job.locked_at = now_started
    job.locked_by = job.locked_by or "inline-worker"
    job.attempts += 1
    monitor.last_status = "running"
    monitor.last_error_code = None
    monitor.last_error_message = None
    db.commit()

    # Create CheckRun record
    check_run = CheckRun(
        monitor_id=monitor.id,
        scheduled_for=job.scheduled_at,
        started_at=datetime.now(timezone.utc),
        status="running",
        attempt_number=job.attempts,
    )
    db.add(check_run)
    db.commit()
    db.refresh(check_run)

    # Execute browser capture
    result = await browser_capture_service.capture_page(
        url=monitor.url,
        include_selectors=monitor.include_selectors,
        ignore_selectors=monitor.ignore_selectors,
        numeric_selector=monitor.numeric_selector,
        allow_test_fixtures=allow_test_fixtures,
    )

    check_run.finished_at = datetime.now(timezone.utc)
    check_run.duration_ms = result.duration_ms
    check_run.http_status = result.http_status
    check_run.capture_metadata = result.metadata

    if not result.success:
        check_run.status = "error" if result.failure_code != "BLOCKED_DESTINATION" else "blocked"
        check_run.failure_code = result.failure_code
        check_run.safe_error_message = result.error_message
        monitor.last_status = check_run.status
        monitor.last_error_code = result.failure_code
        monitor.last_error_message = result.error_message
        monitor.last_checked_at = datetime.now(timezone.utc)

        # Even permanent capture/configuration failures should receive a next-check
        # timestamp so the scheduler doesn't enqueue a fresh job every tick.
        now_failed = datetime.now(timezone.utc)
        monitor.next_check_at = now_failed + timedelta(minutes=max(15, monitor.interval_minutes))

        # Configuration/authentication failures won't heal with retries. Other
        # capture failures receive bounded exponential backoff instead of a hot loop.
        terminal_failures = {
            "BROWSER_WORKER_UNCONFIGURED",
            "BROWSER_WORKER_AUTH_FAILED",
        }
        can_retry = job.attempts < job.max_attempts and result.failure_code not in terminal_failures
        if can_retry:
            job.status = "pending"
            job.scheduled_at = now_failed + timedelta(seconds=min(300, 5 * (2 ** (job.attempts - 1))))
            monitor.last_status = "pending"
        else:
            job.status = "failed"
            job.completed_at = now_failed
            monitor.last_status = check_run.status
        job.locked_at = None
        job.locked_by = None
        job.error_message = result.error_message
        db.commit()
        return False

    # Normalize content and compute hash
    normalized_text, content_hash = compute_normalized_content(
        result.raw_text,
        sensitivity=monitor.sensitivity
    )
    check_run.content_hash = content_hash

    # Fetch last version
    last_version = None
    if monitor.last_version_id:
        last_version = db.query(Version).filter(Version.id == monitor.last_version_id).first()

    now = datetime.now(timezone.utc)
    monitor.last_checked_at = now

    # Record numeric observation if available
    num_raw = result.metadata.get("numeric_text") if result.metadata else None
    if num_raw:
        parsed = parse_numeric_value(num_raw)
        if parsed:
            val, unit, raw_clean = parsed
            obs = NumericObservation(
                monitor_id=monitor.id,
                value=val,
                unit=unit,
                raw_text=raw_clean,
            )
            db.add(obs)
            db.commit()

    if last_version is None:
        # Initial baseline snapshot
        version_id = str(uuid.uuid4())
        screenshot_key = _try_save_screenshot(result.screenshot_bytes, monitor.id, version_id)

        version = Version(
            id=version_id,
            monitor_id=monitor.id,
            check_run_id=check_run.id,
            version_number=1,
            content_hash=content_hash,
            normalized_text=normalized_text,
            screenshot_artifact_key=screenshot_key,
            reason="baseline",
            capture_metadata=result.metadata,
        )
        db.add(version)
        db.commit()

        check_run.status = "ok"
        check_run.changed = False
        monitor.last_version_id = version.id
        monitor.last_status = "ok"
        monitor.last_error_code = None
        monitor.last_error_message = None

    elif last_version.content_hash != content_hash and is_meaningful_change(last_version.normalized_text, normalized_text, monitor.sensitivity):
        # Meaningful change detected!
        version_id = str(uuid.uuid4())
        screenshot_key = _try_save_screenshot(result.screenshot_bytes, monitor.id, version_id)

        next_version_num = (last_version.version_number or 1) + 1
        version = Version(
            id=version_id,
            monitor_id=monitor.id,
            check_run_id=check_run.id,
            version_number=next_version_num,
            content_hash=content_hash,
            normalized_text=normalized_text,
            screenshot_artifact_key=screenshot_key,
            reason="content_changed",
            capture_metadata=result.metadata,
        )
        db.add(version)
        db.commit()

        check_run.status = "ok"
        check_run.changed = True
        monitor.last_version_id = version.id
        monitor.last_changed_at = now
        monitor.last_status = "ok"
        monitor.last_error_code = None
        monitor.last_error_message = None

        # Generate text diff summary & snippet
        diff_items = generate_text_diff(last_version.normalized_text, normalized_text)
        summary = generate_diff_summary(diff_items)

        # Build clean snippet
        diff_lines = []
        for item in diff_items[:20]:
            if item["type"] == "add":
                diff_lines.append(f"+ {item['text']}")
            elif item["type"] == "del":
                diff_lines.append(f"- {item['text']}")
        snippet = "\n".join(diff_lines)

        # Precompute visual diff image if previous screenshot exists
        if last_version.screenshot_artifact_key:
            prev_bytes = _try_read_screenshot(last_version.screenshot_artifact_key)
            if prev_bytes:
                try:
                    diff_png, _ = generate_visual_diff(prev_bytes, result.screenshot_bytes)
                    artifact_storage.save_diff_image(diff_png, monitor.id, f"{last_version.id}_{version.id}")
                except Exception as e:
                    logger.warning("Could not pregenerate visual diff: %s", str(e))

        # Keyword filtering check (FR-10): only alert if keywords match or none specified
        should_alert = matches_keyword_filter(diff_items, monitor.keywords)

        if should_alert:
            # Create alert event with deduplication key
            event_dedupe = f"{monitor.id}:{version.id}"
            alert_event = AlertEvent(
                monitor_id=monitor.id,
                version_id=version.id,
                dedupe_key=event_dedupe,
                summary=summary,
                diff_snippet=snippet,
            )
            db.add(alert_event)
            db.commit()

            # Dispatch alerts to configured channels
            comp_url = f"{settings.APP_BASE_URL}/monitors/{monitor.id}/diff?from={last_version.id}&to={version.id}"
            await dispatch_alert_event(db, alert_event, comp_url)

    else:
        # Unchanged content check
        check_run.status = "ok"
        check_run.changed = False
        monitor.last_status = "ok"
        monitor.last_error_code = None
        monitor.last_error_message = None
        # Discard temporary screenshot & text to satisfy store-on-change requirement

    # Schedule next run with 5-10% jitter
    jitter_mins = random.uniform(-0.05, 0.05) * monitor.interval_minutes
    effective_interval = max(15, monitor.interval_minutes + jitter_mins)
    monitor.next_check_at = now + timedelta(minutes=effective_interval)

    job.status = "completed"
    job.completed_at = now
    job.locked_at = None
    job.locked_by = None
    job.error_message = None
    db.commit()
    return True



async def process_check_job(db: Session, job: QueueJob, allow_test_fixtures: bool = False) -> bool:
    """Run one queue job and ensure unexpected exceptions cannot leave it stuck running."""
    job_id = job.id
    try:
        return await _process_check_job_impl(db, job, allow_test_fixtures=allow_test_fixtures)
    except Exception as exc:
        logger.exception("Unexpected exception processing monitor job %s", job_id)
        db.rollback()
        fresh_job = db.query(QueueJob).filter(QueueJob.id == job_id).first()
        if fresh_job is None:
            return False

        now = datetime.now(timezone.utc)
        monitor_id = fresh_job.payload.get("monitor_id")
        monitor = db.query(Monitor).filter(Monitor.id == monitor_id).first()
        running_run = (
            db.query(CheckRun)
            .filter(CheckRun.monitor_id == monitor_id, CheckRun.status == "running")
            .order_by(CheckRun.started_at.desc())
            .first()
        )
        safe_message = "The check stopped unexpectedly. Review worker logs for details."
        if running_run:
            running_run.status = "error"
            running_run.finished_at = now
            running_run.failure_code = "WORKER_EXCEPTION"
            running_run.safe_error_message = safe_message

        retryable = fresh_job.attempts < fresh_job.max_attempts
        if retryable:
            fresh_job.status = "pending"
            fresh_job.scheduled_at = now + timedelta(seconds=min(300, 5 * (2 ** max(0, fresh_job.attempts - 1))))
            fresh_job.error_message = safe_message
            if monitor:
                monitor.last_status = "pending"
                monitor.last_error_code = "WORKER_EXCEPTION"
                monitor.last_error_message = safe_message
        else:
            fresh_job.status = "failed"
            fresh_job.completed_at = now
            fresh_job.error_message = safe_message
            if monitor:
                monitor.last_status = "error"
                monitor.last_error_code = "WORKER_EXCEPTION"
                monitor.last_error_message = safe_message
                monitor.last_checked_at = now
                monitor.next_check_at = now + timedelta(minutes=max(15, monitor.interval_minutes))
        fresh_job.locked_at = None
        fresh_job.locked_by = None
        db.commit()
        return False
