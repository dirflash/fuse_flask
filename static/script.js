  // mobile menu
  const burgerIcon = document.querySelector('#burger');
  const navbarMenu = document.querySelector('#nav-links');

  burgerIcon.addEventListener('click', () => {
    navbarMenu.classList.toggle('is-active');
  });

  // notification delete
  document.addEventListener('DOMContentLoaded', () => {
    (document.querySelectorAll('.notification .delete') || []).forEach(($delete) => {
      const $notification = $delete.parentNode;

      $delete.addEventListener('click', () => {
        $notification.parentNode.removeChild($notification);
      });
    });
  });


// Update file name display
const fileInput = document.getElementById('fuse_file');
fileInput.addEventListener('change', function() {
  const fileNameDisplay = document.getElementById('file_name_display');
  if (fileInput.files.length > 0) {
    fileNameDisplay.textContent = fileInput.files[0].name;
  } else {
    fileNameDisplay.textContent = 'No file uploaded';
  }
});

// Submit form with fetch
/** @param {Event} event */
function handleSubmit(event) {
  const form = event.currentTarget;
  const url = new URL(form.action);
  const formData = new FormData(form);
  const searchParams = new URLSearchParams(formData);
  /** @type {Parameters<fetch>[1]} */
  const fetchOptions = {
    method: form.method,
  };

  if (form.method.toLowerCase() === 'post') {
    fetchOptions.body = formData.enctype === 'multipart/form-data' ? formData : searchParams;
  } else {
    url.search = searchParams;
  }
  fetch(url, fetchOptions);
  event.preventDefault();
}