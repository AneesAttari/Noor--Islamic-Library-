/* Global UI helpers: image fallback for covers. */
(function () {
  'use strict';

  // If a cover image fails to load, fall back to the generated SVG endpoint.
  document.addEventListener('error', function (event) {
    var el = event.target;
    if (el && el.tagName === 'IMG' && el.dataset.fallbackTried !== '1') {
      el.dataset.fallbackTried = '1';
      var base = el.getAttribute('src') || '';
      if (base.indexOf('/cover') === -1) return;
      // Strip any query so the SVG placeholder route is used cleanly.
      el.src = base.split('?')[0];
    }
  }, true);
})();
