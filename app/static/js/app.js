// ChangeWatch Client App Scripts

// 1. Theme Management (Light / Dark)
function applyTheme(theme) {
  if (theme === 'dark') {
    document.documentElement.classList.add('dark');
  } else if (theme === 'light') {
    document.documentElement.classList.remove('dark');
  } else {
    // System preference
    if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) {
      document.documentElement.classList.add('dark');
    } else {
      document.documentElement.classList.remove('dark');
    }
  }
  updateThemeIcons();
}

function toggleTheme() {
  const isDark = document.documentElement.classList.contains('dark');
  const nextTheme = isDark ? 'light' : 'dark';
  localStorage.setItem('cw_theme', nextTheme);
  applyTheme(nextTheme);
}

function updateThemeIcons() {
  const isDark = document.documentElement.classList.contains('dark');
  document.querySelectorAll('.theme-icon-sun').forEach(el => {
    el.classList.toggle('hidden', !isDark);
  });
  document.querySelectorAll('.theme-icon-moon').forEach(el => {
    el.classList.toggle('hidden', isDark);
  });
  document.querySelectorAll('.theme-label').forEach(el => {
    el.textContent = isDark ? 'Dark Mode' : 'Light Mode';
  });
}

// 2. Windows PC & Reduced Motion Optimization
function applyMotion(motion) {
  if (motion === 'reduced') {
    document.documentElement.classList.add('reduced-motion');
  } else if (motion === 'normal') {
    document.documentElement.classList.remove('reduced-motion');
  } else {
    // System preference (Windows Accessibility: Show animations off)
    if (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      document.documentElement.classList.add('reduced-motion');
    } else {
      document.documentElement.classList.remove('reduced-motion');
    }
  }
  updateMotionIcons();
}

function toggleMotion() {
  const isReduced = document.documentElement.classList.contains('reduced-motion');
  const nextMotion = isReduced ? 'normal' : 'reduced';
  localStorage.setItem('cw_motion', nextMotion);
  applyMotion(nextMotion);
}

function updateMotionIcons() {
  const isReduced = document.documentElement.classList.contains('reduced-motion');
  document.querySelectorAll('.motion-indicator').forEach(el => {
    el.classList.toggle('bg-amber-400', isReduced);
    el.classList.toggle('bg-emerald-400', !isReduced);
  });
  document.querySelectorAll('.motion-label').forEach(el => {
    el.textContent = isReduced ? 'Motion: Off (Optimized)' : 'Motion: Fluid';
  });
}

// OS Listeners
if (window.matchMedia) {
  window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
    if (!localStorage.getItem('cw_theme')) {
      applyTheme('system');
    }
  });
  window.matchMedia('(prefers-reduced-motion: reduce)').addEventListener('change', () => {
    if (!localStorage.getItem('cw_motion')) {
      applyMotion('system');
    }
  });
}

// Initialize button icons on DOMContentLoaded
document.addEventListener('DOMContentLoaded', () => {
  updateThemeIcons();
  updateMotionIcons();
});

// 3. Konami Code Easter Egg: Up, Up, Down, Down, Left, Right, Left, Right, B, A
(function initKonami() {
  const konamiSequence = [
    'ArrowUp', 'ArrowUp',
    'ArrowDown', 'ArrowDown',
    'ArrowLeft', 'ArrowRight',
    'ArrowLeft', 'ArrowRight',
    'KeyB', 'KeyA'
  ];
  let konamiIndex = 0;

  window.addEventListener('keydown', (e) => {
    const expected = konamiSequence[konamiIndex];
    if (e.code === expected || (expected === 'KeyB' && e.key.toLowerCase() === 'b') || (expected === 'KeyA' && e.key.toLowerCase() === 'a')) {
      konamiIndex++;
      if (konamiIndex === konamiSequence.length) {
        konamiIndex = 0;
        triggerKonamiEgg();
      }
    } else {
      konamiIndex = 0;
    }
  });

  function triggerKonamiEgg() {
    const overlay = document.getElementById('konami-overlay');
    if (overlay) {
      overlay.classList.remove('hidden');
      console.log('🛸 KONAMI CODE ACTIVATED: GOD MODE TURBO MONITORING');
    }
  }
})();

// 4. Helpers for copy to clipboard
function copyToClipboard(text, btnElement) {
  if (navigator.clipboard) {
    navigator.clipboard.writeText(text).then(() => {
      const original = btnElement.innerText;
      btnElement.innerText = 'Copied!';
      setTimeout(() => { btnElement.innerText = original; }, 2000);
    });
  }
}

// 5. Mobile Navigation Drawer Controller
function toggleMobileNav() {
  const sheet = document.getElementById('mobile-nav-sheet');
  const backdrop = document.getElementById('mobile-nav-backdrop');
  const btn = document.getElementById('mobile-menu-btn');
  if (!sheet || !backdrop) return;

  const isOpen = !sheet.classList.contains('translate-x-full');
  if (isOpen) {
    sheet.classList.add('translate-x-full');
    backdrop.classList.add('hidden');
    if (btn) btn.setAttribute('aria-expanded', 'false');
    document.body.classList.remove('overflow-hidden');
  } else {
    sheet.classList.remove('translate-x-full');
    backdrop.classList.remove('hidden');
    if (btn) btn.setAttribute('aria-expanded', 'true');
    document.body.classList.add('overflow-hidden');
  }
}

// Close mobile nav when Esc is pressed
window.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') {
    const sheet = document.getElementById('mobile-nav-sheet');
    if (sheet && !sheet.classList.contains('translate-x-full')) {
      toggleMobileNav();
    }
  }
});

