/* Admin UI: confirmations, upload labels, and PDF metadata auto-fill. */
(function () {
  'use strict';

  document.querySelectorAll('form.confirm-delete').forEach(function (form) {
    form.addEventListener('submit', function (event) {
      var title = form.dataset.title || 'this book';
      if (!window.confirm('Move “' + title + '” to the trash?\n\nIt can be restored from the Trash page, or deleted forever there.')) {
        event.preventDefault();
      }
    });
  });

  document.querySelectorAll('form.confirm-purge').forEach(function (form) {
    form.addEventListener('submit', function (event) {
      var title = form.dataset.title || 'this book';
      if (!window.confirm('PERMANENTLY delete “' + title + '”?\n\nThis removes the book record and every stored file (PDF, covers, revisions). This cannot be undone.')) {
        event.preventDefault();
      }
    });
  });

  document.querySelectorAll('form.confirm-restore').forEach(function (form) {
    form.addEventListener('submit', function (event) {
      if (!window.confirm('Restore this earlier PDF version?\n\nThe current PDF will be kept as a revision, so you can swap back.')) {
        event.preventDefault();
      }
    });
  });

  document.querySelectorAll('form.confirm-delete-msg').forEach(function (form) {
    form.addEventListener('submit', function (event) {
      if (!window.confirm('Delete this message permanently?')) {
        event.preventDefault();
      }
    });
  });

  // Show the chosen file name next to file inputs for clarity.
  document.querySelectorAll('input[type="file"]').forEach(function (input) {
    input.addEventListener('change', function () {
      var hint = input.parentElement.querySelector('.file-name');
      if (!hint) {
        hint = document.createElement('p');
        hint.className = 'hint file-name';
        input.insertAdjacentElement('afterend', hint);
      }
      hint.textContent = input.files && input.files.length
        ? 'Selected: ' + Array.prototype.map.call(input.files, function (f) { return f.name; }).join(', ')
        : '';
    });
  });

  // Bulk upload: show how many files are queued.
  var bulkInput = document.getElementById('pdfs');
  if (bulkInput) {
    bulkInput.addEventListener('change', function () {
      var n = bulkInput.files ? bulkInput.files.length : 0;
      var label = document.getElementById('bulk-count');
      if (label) {
        label.textContent = n ? (n + ' file(s) queued for upload.') : 'Select one or more PDFs (up to 100 MB each).';
      }
    });
  }

  // Single-book form: read embedded PDF metadata and pre-fill empty fields.
  var pdfInput = document.getElementById('pdf');
  if (pdfInput && pdfInput.dataset.probeUrl) {
    pdfInput.addEventListener('change', function () {
      var file = pdfInput.files && pdfInput.files[0];
      if (!file) return;
      var status = document.getElementById('pdf-probe-status');
      var titleField = document.getElementById('title');
      var authorField = document.getElementById('author');
      if (status) status.textContent = 'Reading PDF metadata…';

      var form = new FormData();
      form.append('pdf', file);
      var csrf = document.querySelector('input[name="csrf_token"]');
      if (csrf) form.append('csrf_token', csrf.value);

      fetch(pdfInput.dataset.probeUrl, { method: 'POST', body: form, credentials: 'same-origin' })
        .then(function (resp) { return resp.json().then(function (data) { return { ok: resp.ok, data: data }; }); })
        .then(function (result) {
          var data = result.data || {};
          if (!result.ok || !data.ok) {
            if (status) status.textContent = 'Could not read metadata: ' + (data.error || 'unknown error') + ' You can type the details yourself.';
            return;
          }
          var filled = [];
          if (titleField && !titleField.value.trim() && data.title) {
            titleField.value = data.title;
            filled.push('title');
          }
          if (authorField && !authorField.value.trim() && data.author) {
            authorField.value = data.author;
            filled.push('author');
          }
          if (status) {
            status.textContent = 'PDF OK — ' + data.page_count + ' pages.' +
              (filled.length ? ' Filled ' + filled.join(' and ') + ' from the PDF metadata (you can edit).' : ' Fill in the details below.');
          }
        })
        .catch(function () {
          if (status) status.textContent = 'Metadata check failed — you can type the details yourself.';
        });
    });
  }
})();
