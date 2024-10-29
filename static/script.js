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
if (fileInput) {
  fileInput.addEventListener('change', function() {
    const fileNameDisplay = document.getElementById('file_name_display');
    if (fileNameDisplay) {
      if (fileInput.files.length > 0) {
        fileNameDisplay.textContent = fileInput.files[0].name;
      } else {
        fileNameDisplay.textContent = 'No file uploaded';
      }
    } else {
      console.error('Element with ID "file_name_display" not found.');
    }
  });
} else {
  console.error('Element with ID "fuse_file" not found.');
  const fileNameDisplay = document.getElementById('file_name_display');
  if (fileNameDisplay) {
    fileNameDisplay.textContent = 'No file uploaded';
  }
}

// Ensure the DOM is fully loaded before running the script
document.addEventListener('DOMContentLoaded', function() {
  // Update file name display
  const fileInput = document.getElementById('fuse_file');
  if (fileInput) {
      fileInput.addEventListener('change', function() {
          const fileNameDisplay = document.getElementById('file_name_display');
          if (fileInput.files.length > 0) {
              fileNameDisplay.textContent = fileInput.files[0].name;
          } else {
              fileNameDisplay.textContent = 'No file uploaded';
          }
      });
  }

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
  };

  // Reload page on mode change
  const modeSelect = document.getElementById('mode-select');
  if (modeSelect) {
    modeSelect.addEventListener('change', function() {
      // Update the 'mode' value in the Flask session
      fetch('/update-mode', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': getCookie('csrf_token') // Ensure CSRF protection
        },
        body: JSON.stringify({ mode: modeSelect.value })
      })
      .then(response => {
        if (response.ok) {
          // Reload the current page
          location.reload();
        } else {
          console.error('Failed to update mode in session.');
        }
      })
      .catch(error => {
        console.error('Error:', error);
      });
    });
  }

  // Function to get a cookie value by name
  function getCookie(name) {
    const value = `; ${document.cookie}`;
    const parts = value.split(`; ${name}=`);
    if (parts.length === 2) return parts.pop().split(';').shift();
  }
});
