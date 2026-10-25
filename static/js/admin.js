/* Admin UI: delete confirmations and upload labels. */
(function () {
  'use strict';

  document.querySelectorAll('form.confirm-delete').forEach(function (form) {
    form.addEventListener('submit', function (event) {
      var title = form.dataset.title || 'this book';
      if (!window.confirm('Delete “' + title + '”?\n\nThis permanently removes the book record and its stored PDF and cover files. This cannot be undone.')) {
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
        ? 'Selected: ' + input.files[0].name
        : '';
    });
  });
})();
