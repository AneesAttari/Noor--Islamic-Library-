/* Global UI helpers: cover fallback, continue-reading, service worker. */
(function () {
  'use strict';

  // If a cover image fails to load, fall back to the generated SVG endpoint.
  document.addEventListener('error', function (event) {
    var el = event.target;
    if (el && el.tagName === 'IMG' && el.dataset.fallbackTried !== '1') {
      el.dataset.fallbackTried = '1';
      var base = el.getAttribute('src') || '';
      if (base.indexOf('/cover') === -1) return;
      el.src = base.split('?')[0];
    }
  }, true);

  // "Continue reading — page N" on book detail pages (position from localStorage).
  document.addEventListener('DOMContentLoaded', function () {
    var btn = document.getElementById('read-btn');
    if (btn && btn.dataset.bookId) {
      try {
        var raw = localStorage.getItem('maktaba:pos:' + btn.dataset.bookId);
        var pos = raw ? JSON.parse(raw) : null;
        if (pos && pos.page > 1) {
          btn.textContent = 'Continue reading — page ' + pos.page;
          btn.href = btn.href.split('?')[0] + '?p=' + pos.page;
        }
      } catch (e) {}
    }
    var printBtn = document.getElementById('print-btn');
    if (printBtn) {
      printBtn.addEventListener('click', function () { window.print(); });
    }
  });

  // PWA: cache the static shell so the library works from the home screen.
  if ('serviceWorker' in navigator && location.protocol.indexOf('http') === 0) {
    window.addEventListener('load', function () {
      try {
        navigator.serviceWorker.register('/static/js/sw.js', { scope: '/' }).catch(function () {});
      } catch (e) {}
    });
  }
})();
