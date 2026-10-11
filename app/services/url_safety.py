import ipaddress
import socket
from urllib.parse import urlparse
from typing import Tuple, List, Optional


DISALLOWED_HOSTNAMES = {
    "localhost",
    "127.0.0.1",
    "::1",
    "metadata.google.internal",
    "instance-data",
}

DISALLOWED_IPV4_NETWORKS = [
    ipaddress.ip_network("0.0.0.0/8"),          # Current network
    ipaddress.ip_network("10.0.0.0/8"),         # Private RFC 1918
    ipaddress.ip_network("100.64.0.0/10"),      # Carrier-grade NAT
    ipaddress.ip_network("127.0.0.0/8"),        # Loopback
    ipaddress.ip_network("169.254.0.0/16"),     # Link-local / Cloud metadata
    ipaddress.ip_network("172.16.0.0/12"),      # Private RFC 1918
    ipaddress.ip_network("192.0.0.0/24"),       # IETF Protocol Assignments
    ipaddress.ip_network("192.0.2.0/24"),       # Documentation (TEST-NET-1)
    ipaddress.ip_network("192.168.0.0/16"),     # Private RFC 1918
    ipaddress.ip_network("198.18.0.0/15"),      # Benchmarking
    ipaddress.ip_network("198.51.100.0/24"),    # Documentation (TEST-NET-2)
    ipaddress.ip_network("203.0.113.0/24"),     # Documentation (TEST-NET-3)
    ipaddress.ip_network("224.0.0.0/4"),        # Multicast
    ipaddress.ip_network("240.0.0.0/4"),        # Reserved / Future use
    ipaddress.ip_network("255.255.255.255/32"), # Broadcast
]

DISALLOWED_IPV6_NETWORKS = [
    ipaddress.ip_network("::1/128"),            # Loopback
    ipaddress.ip_network("::/128"),             # Unspecified
    ipaddress.ip_network("fc00::/7"),           # Unique Local Address (ULA)
    ipaddress.ip_network("fe80::/10"),          # Link-local
    ipaddress.ip_network("ff00::/8"),           # Multicast
    ipaddress.ip_network("2001:db8::/32"),      # Documentation
]


class URLSafetyError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def is_ip_disallowed(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified:
        return True

    if isinstance(ip, ipaddress.IPv4Address):
        for network in DISALLOWED_IPV4_NETWORKS:
            if ip in network:
                return True
    elif isinstance(ip, ipaddress.IPv6Address):
        for network in DISALLOWED_IPV6_NETWORKS:
            if ip in network:
                return True
    return False


def validate_public_url(url: str, allow_test_fixtures: bool = False) -> Tuple[bool, str, Optional[str]]:
    """
    Validates that a URL is a valid public HTTP/HTTPS target.
    Returns: (is_safe, canonical_url_or_error, failure_code)
    """
    if not url or not isinstance(url, str):
        return False, "URL cannot be empty", "INVALID_URL"

    parsed = urlparse(url.strip())

    if parsed.scheme.lower() not in ("http", "https"):
        return False, f"Unsupported scheme '{parsed.scheme}'. Only http and https are permitted.", "INVALID_SCHEME"

    if parsed.username or parsed.password:
        return False, "URLs with embedded credentials are not allowed.", "CREDENTIALS_DISALLOWED"

    hostname = parsed.hostname
    if not hostname:
        return False, "Malformed URL missing valid hostname.", "MALFORMED_HOSTNAME"

    hostname_lower = hostname.lower()

    if allow_test_fixtures and (hostname_lower in ("127.0.0.1", "localhost", "testserver")):
        return True, url, None

    if hostname_lower in DISALLOWED_HOSTNAMES or hostname_lower.endswith(".localhost"):
        return False, f"Hostname '{hostname}' points to a disallowed local/internal target.", "BLOCKED_DESTINATION"

    # Resolve hostname to all IP addresses
    try:
        port = parsed.port or (443 if parsed.scheme.lower() == "https" else 80)
        addr_infos = socket.getaddrinfo(hostname, port, socket.AF_UNSPEC, socket.SOCK_STREAM)
    except socket.gaierror as e:
        return False, f"DNS resolution failed for hostname '{hostname}'.", "DNS_RESOLUTION_FAILED"
    except Exception as e:
        return False, f"Network resolution error: {str(e)}", "DNS_RESOLUTION_FAILED"

    if not addr_infos:
        return False, f"No IP address records found for hostname '{hostname}'.", "NO_DNS_RECORDS"

    # Check each resolved address
    for family, socktype, proto, canonname, sockaddr in addr_infos:
        ip_str = sockaddr[0]
        try:
            ip_obj = ipaddress.ip_address(ip_str)
            if is_ip_disallowed(ip_obj):
                return False, f"Destination resolved to private or restricted IP address.", "PRIVATE_IP_BLOCKED"
        except ValueError:
            return False, f"Invalid IP address returned for host.", "INVALID_IP"

    # Normalized canonical URL
    port_str = f":{parsed.port}" if parsed.port and parsed.port not in (80, 443) else ""
    canonical = f"{parsed.scheme.lower()}://{hostname_lower}{port_str}{parsed.path or '/'}"
    if parsed.query:
        canonical += f"?{parsed.query}"

    return True, canonical, None
