/* Colour themes: Light (ivory), Dark, Warm. Applied before first paint to
   avoid flashing; the visitor's choice is remembered in localStorage. */
(function () {
  'use strict';
  var THEMES = ['light', 'dark', 'warm'];
  var LABELS = { light: 'Light', dark: 'Dark', warm: 'Warm' };

  function current() {
    try {
      var saved = localStorage.getItem('maktaba:theme');
      return saved && THEMES.indexOf(saved) !== -1 ? saved : 'light';
    } catch (e) { return 'light'; }
  }

  function apply(theme) {
    document.documentElement.setAttribute('data-theme', theme);
    try { localStorage.setItem('maktaba:theme', theme); } catch (e) {}
    var meta = document.querySelector('meta[name="theme-color"]');
    if (meta) {
      meta.setAttribute('content', theme === 'dark' ? '#1a1815' : (theme === 'warm' ? '#f0e4c8' : '#0f6b4f'));
    }
    var btn = document.getElementById('theme-toggle');
    if (btn) {
      btn.textContent = LABELS[theme];
      btn.setAttribute('aria-label', 'Colour theme: ' + LABELS[theme] + '. Click to change.');
    }
  }

  // set immediately (this file loads synchronously in <head>)
  apply(current());

  document.addEventListener('DOMContentLoaded', function () {
    apply(current());
    var btn = document.getElementById('theme-toggle');
    if (btn) {
      btn.addEventListener('click', function () {
        var next = THEMES[(THEMES.indexOf(current()) + 1) % THEMES.length];
        apply(next);
      });
    }
  });
})();
