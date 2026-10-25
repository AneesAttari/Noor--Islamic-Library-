/* PDF reader: page navigation, zoom, single/continuous modes, resume.
   Uses pdf.js (vendored locally). Reading positions are saved per book in
   localStorage — no account, no server-side tracking of individuals. */
(function () {
  'use strict';

  var stage = document.querySelector('.reader');
  if (!stage || typeof pdfjsLib === 'undefined') return;

  var pdfUrl = stage.dataset.pdfUrl;
  var bookId = stage.dataset.bookId;
  var canvas = document.getElementById('pdf-canvas');
  var ctx = canvas.getContext('2d');

  var loadingEl = document.getElementById('reader-loading');
  var errorEl = document.getElementById('reader-error');
  var errorMsg = document.getElementById('reader-error-msg');
  var pageInput = document.getElementById('page-input');
  var pageCountEl = document.getElementById('page-count');
  var zoomLevelEl = document.getElementById('zoom-level');
  var progressBar = document.getElementById('progress-bar');
  var announceEl = document.getElementById('page-announce');
  var resumeBar = document.getElementById('resume-bar');
  var resumeText = document.getElementById('resume-text');
  var scrollContainer = document.getElementById('scroll-container');

  pdfjsLib.GlobalWorkerOptions.workerSrc =
    (document.querySelector('script[src*="pdf.min.js"]').src || '/static/vendor/pdfjs/pdf.min.js')
      .replace('pdf.min.js', 'pdf.worker.min.js');

  var pdfDoc = null;
  var pageNum = 1;
  var scale = 1.0;
  var fitMode = true;
  var mode = 'single';           // 'single' | 'continuous'
  var pageRendering = false;
  var pendingPage = null;
  var MIN_SCALE = 0.25;
  var MAX_SCALE = 4.0;

  // continuous-mode state
  var rendered = {};             // pageNum -> {slot, canvas, task}
  var scrollObserver = null;
  var saveTimer = null;

  // ---------- position memory ---------------------------------------------

  function posKey() { return 'maktaba:pos:' + bookId; }

  function loadPos() {
    try {
      var raw = localStorage.getItem(posKey());
      return raw ? JSON.parse(raw) : null;
    } catch (e) { return null; }
  }

  function savePos() {
    try {
      localStorage.setItem(posKey(), JSON.stringify({ page: pageNum, ts: Date.now() }));
    } catch (e) {}
  }

  function scheduleSave() {
    clearTimeout(saveTimer);
    saveTimer = setTimeout(savePos, 400);
  }

  // ---------- shared UI ----------------------------------------------------

  function setLoading(on) { loadingEl.hidden = !on; }

  function showError(message) {
    setLoading(false);
    canvas.hidden = true;
    scrollContainer.hidden = true;
    errorEl.hidden = false;
    errorMsg.textContent = message;
  }

  function updateControls() {
    var total = pdfDoc ? pdfDoc.numPages : 1;
    pageInput.value = String(pageNum);
    pageInput.max = String(total);
    pageCountEl.textContent = pdfDoc ? String(total) : '–';
    zoomLevelEl.textContent = Math.round(scale * 100) + '%';
    var atStart = pageNum <= 1;
    var atEnd = !pdfDoc || pageNum >= pdfDoc.numPages;
    document.getElementById('btn-prev').disabled = atStart;
    document.getElementById('btn-next').disabled = atEnd;
    document.getElementById('btn-prev-m').disabled = atStart;
    document.getElementById('btn-next-m').disabled = atEnd;
    var pct = pdfDoc ? Math.round((pageNum / pdfDoc.numPages) * 100) : 0;
    progressBar.style.width = pct + '%';
    announceEl.textContent = 'Page ' + pageNum + ' of ' + (pdfDoc ? pdfDoc.numPages : '?');
    document.getElementById('btn-mode-single').setAttribute('aria-pressed', mode === 'single');
    document.getElementById('btn-mode-scroll').setAttribute('aria-pressed', mode === 'continuous');
    scheduleSave();
  }

  function computeFitScale(viewportWidth) {
    var available = Math.min(stage.clientWidth - 32, 1000);
    return Math.max(MIN_SCALE, Math.min(MAX_SCALE, available / viewportWidth));
  }

  function queueRender(num) {
    if (!pdfDoc) return;
    num = Math.max(1, Math.min(pdfDoc.numPages, num));
    pageNum = num;
    updateControls();
    if (mode === 'continuous') {
      scrollToPage(num);
    } else {
      renderSingle(num);
    }
  }

  // ---------- single-page mode ---------------------------------------------

  function renderSingle(num) {
    if (pageRendering) { pendingPage = num; return; }
    pageRendering = true;
    setLoading(false);
    errorEl.hidden = true;

    pdfDoc.getPage(num).then(function (page) {
      if (fitMode) {
        var base = page.getViewport({ scale: 1.0 });
        scale = computeFitScale(base.width);
      }
      var dpr = Math.min(window.devicePixelRatio || 1, 2);
      var viewport = page.getViewport({ scale: scale });
      var renderViewport = page.getViewport({ scale: scale * dpr });

      canvas.width = Math.floor(renderViewport.width);
      canvas.height = Math.floor(renderViewport.height);
      canvas.style.width = Math.floor(viewport.width) + 'px';
      canvas.style.height = Math.floor(viewport.height) + 'px';
      canvas.hidden = false;
      ctx.setTransform(1, 0, 0, 1, 0, 0);

      return page.render({ canvasContext: ctx, viewport: renderViewport }).promise;
    }).then(function () {
      pageRendering = false;
      updateControls();
      if (pendingPage !== null && pendingPage !== pageNum) {
        var next = pendingPage;
        pendingPage = null;
        renderSingle(next);
      } else {
        pendingPage = null;
      }
    }).catch(function (err) {
      pageRendering = false;
      console.error(err);
      showError('The PDF failed to render: ' + (err && err.message ? err.message : 'unknown error'));
    });
  }

  // ---------- continuous mode ----------------------------------------------

  function makeSlot(num, pageHeight) {
    var slot = document.createElement('div');
    slot.className = 'page-slot';
    slot.dataset.page = String(num);
    slot.style.height = pageHeight + 'px';

    var label = document.createElement('p');
    label.className = 'page-slot-label';
    label.textContent = 'Page ' + num;
    slot.appendChild(label);

    scrollContainer.appendChild(slot);
    return slot;
  }

  function renderSlot(num) {
    if (!pdfDoc || rendered[num]) return;
    var total = pdfDoc.numPages;
    pdfDoc.getPage(num).then(function (page) {
      var dpr = Math.min(window.devicePixelRatio || 1, 1.5);
      var viewport = page.getViewport({ scale: scale });
      var renderViewport = page.getViewport({ scale: scale * dpr });

      var slot = scrollContainer.querySelector('.page-slot[data-page="' + num + '"]');
      if (!slot) {
        slot = makeSlot(num, viewport.height + 28);
      } else {
        slot.style.height = (viewport.height + 28) + 'px';
      }

      var cv = slot.querySelector('canvas');
      if (!cv) {
        cv = document.createElement('canvas');
        slot.appendChild(cv);
      }
      cv.width = Math.floor(renderViewport.width);
      cv.height = Math.floor(renderViewport.height);
      cv.style.width = Math.floor(viewport.width) + 'px';
      cv.style.height = Math.floor(viewport.height) + 'px';

      var task = page.render({
        canvasContext: cv.getContext('2d'),
        viewport: renderViewport
      });
      rendered[num] = { slot: slot, canvas: cv, task: task };
      return task.promise;
    }).catch(function (err) {
      console.error('page render failed', num, err);
    });
  }

  function dropFarPages(around) {
    Object.keys(rendered).forEach(function (key) {
      var num = parseInt(key, 10);
      if (Math.abs(num - around) > 3 && rendered[num]) {
        var entry = rendered[num];
        if (entry.task && entry.task.cancel) {
          try { entry.task.cancel(); } catch (e) {}
        }
        var cv = entry.slot.querySelector('canvas');
        if (cv) entry.slot.removeChild(cv);
        delete rendered[num];
      }
    });
  }

  function ensureSlots() {
    pdfDoc.getPage(1).then(function (page) {
      var base = page.getViewport({ scale: 1.0 });
      if (fitMode) scale = computeFitScale(base.width);
      var h = base.height * scale + 28;
      var existing = scrollContainer.querySelectorAll('.page-slot').length;
      if (existing !== pdfDoc.numPages) {
        scrollContainer.innerHTML = '';
        rendered = {};
        for (var i = 1; i <= pdfDoc.numPages; i++) {
          makeSlot(i, h);
        }
      }
      setupObserver();
      renderSlot(pageNum);
      renderSlot(Math.min(pageNum + 1, pdfDoc.numPages));
      renderSlot(Math.max(pageNum - 1, 1));
      scrollToPage(pageNum, true);
    });
  }

  function setupObserver() {
    if (scrollObserver) scrollObserver.disconnect();
    scrollObserver = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (!entry.isIntersecting) return;
        var num = parseInt(entry.target.dataset.page, 10);
        if (!isNaN(num) && num !== pageNum) {
          pageNum = num;
          updateControls();
        }
        renderSlot(num);
        renderSlot(num + 1);
        renderSlot(num - 1);
        dropFarPages(num);
      });
    }, {
      root: null,
      rootMargin: '600px 0px 600px 0px',
      threshold: 0.25
    });
    scrollContainer.querySelectorAll('.page-slot').forEach(function (slot) {
      scrollObserver.observe(slot);
    });
  }

  function scrollToPage(num, instant) {
    var slot = scrollContainer.querySelector('.page-slot[data-page="' + num + '"]');
    if (slot) {
      slot.scrollIntoView({ behavior: instant ? 'auto' : 'smooth', block: 'start' });
      renderSlot(num);
    }
  }

  // ---------- mode switching -----------------------------------------------

  function setMode(next) {
    if (!pdfDoc) return;
    mode = next;
    if (mode === 'continuous') {
      canvas.hidden = true;
      scrollContainer.hidden = false;
      ensureSlots();
    } else {
      scrollContainer.hidden = true;
      scrollContainer.innerHTML = '';
      rendered = {};
      if (scrollObserver) { scrollObserver.disconnect(); scrollObserver = null; }
      renderSingle(pageNum);
    }
    updateControls();
  }

  // ---------- zoom ----------------------------------------------------------

  function setZoom(nextScale) {
    fitMode = false;
    scale = Math.max(MIN_SCALE, Math.min(MAX_SCALE, nextScale));
    if (mode === 'continuous') {
      // rebuild slots at the new scale
      scrollContainer.innerHTML = '';
      rendered = {};
      ensureSlots();
    } else {
      renderSingle(pageNum);
    }
    updateControls();
  }

  function fitWidth() {
    fitMode = true;
    if (!pdfDoc) return;
    if (mode === 'continuous') {
      scrollContainer.innerHTML = '';
      rendered = {};
      ensureSlots();
    } else {
      renderSingle(pageNum);
    }
    updateControls();
  }

  // ---------- wiring ---------------------------------------------------------

  document.getElementById('btn-prev').addEventListener('click', function () { queueRender(pageNum - 1); });
  document.getElementById('btn-next').addEventListener('click', function () { queueRender(pageNum + 1); });
  document.getElementById('btn-prev-m').addEventListener('click', function () { queueRender(pageNum - 1); });
  document.getElementById('btn-next-m').addEventListener('click', function () { queueRender(pageNum + 1); });

  pageInput.addEventListener('change', function () {
    var value = parseInt(pageInput.value, 10);
    if (!isNaN(value)) queueRender(value); else updateControls();
  });
  pageInput.addEventListener('keydown', function (event) {
    if (event.key === 'Enter') {
      event.preventDefault();
      var value = parseInt(pageInput.value, 10);
      if (!isNaN(value)) queueRender(value);
    }
  });

  document.getElementById('btn-zoom-in').addEventListener('click', function () { setZoom(scale * 1.2); });
  document.getElementById('btn-zoom-out').addEventListener('click', function () { setZoom(scale / 1.2); });
  document.getElementById('btn-fit').addEventListener('click', fitWidth);
  document.getElementById('btn-mode-single').addEventListener('click', function () { setMode('single'); });
  document.getElementById('btn-mode-scroll').addEventListener('click', function () { setMode('continuous'); });

  document.addEventListener('keydown', function (event) {
    var tag = (event.target && event.target.tagName) || '';
    if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
    if (mode === 'continuous' && (event.key === 'ArrowRight' || event.key === 'ArrowLeft')) return;
    if (event.key === 'ArrowRight' || event.key === 'PageDown') { event.preventDefault(); queueRender(pageNum + 1); }
    if (event.key === 'ArrowLeft' || event.key === 'PageUp') { event.preventDefault(); queueRender(pageNum - 1); }
    if (event.key === '+' || event.key === '=') { setZoom(scale * 1.2); }
    if (event.key === '-') { setZoom(scale / 1.2); }
  });

  var resizeTimer = null;
  window.addEventListener('resize', function () {
    if (!fitMode || !pdfDoc) return;
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(function () {
      if (mode === 'continuous') {
        scrollContainer.innerHTML = '';
        rendered = {};
        ensureSlots();
      } else {
        renderSingle(pageNum);
      }
    }, 180);
  });

  document.getElementById('btn-retry').addEventListener('click', function () {
    errorEl.hidden = true;
    load();
  });

  // resume bar
  document.getElementById('btn-resume').addEventListener('click', function () {
    var pos = loadPos();
    var target = pos && pos.page > 1 ? pos.page : 1;
    resumeBar.hidden = true;
    queueRender(target);
    if (mode === 'continuous') scrollToPage(target);
  });
  document.getElementById('btn-restart').addEventListener('click', function () {
    resumeBar.hidden = true;
    queueRender(1);
    if (mode === 'continuous') scrollToPage(1);
  });

  // ---------- load -----------------------------------------------------------

  function load() {
    setLoading(true);
    errorEl.hidden = true;
    resumeBar.hidden = true;
    pdfDoc = null;

    pdfjsLib.getDocument({ url: pdfUrl, withCredentials: true }).promise.then(function (doc) {
      if (!doc.numPages) {
        showError('This PDF appears to have no pages.');
        return;
      }
      pdfDoc = doc;

      // where should we open?
      var params = new URLSearchParams(window.location.search);
      var requested = parseInt(params.get('p') || '', 10);
      var pos = loadPos();
      var start = 1;
      if (!isNaN(requested) && requested >= 1) {
        start = Math.min(requested, doc.numPages);
      } else if (pos && pos.page > 1 && pos.page <= doc.numPages) {
        // offer resume instead of jumping silently
        resumeText.textContent = 'You stopped at page ' + pos.page + ' of ' + doc.numPages + '.';
        resumeBar.hidden = false;
        start = 1;
      }
      pageNum = start;
      fitMode = true;
      setMode('single');
      updateControls();
    }).catch(function (err) {
      console.error(err);
      var message = 'The PDF could not be loaded.';
      if (err && err.name === 'InvalidPDFException') message = 'The stored file is not a readable PDF.';
      else if (err && err.status === 404) message = 'The file was not found on the server.';
      showError(message);
    });
  }

  window.addEventListener('beforeunload', savePos);
  load();
})();
