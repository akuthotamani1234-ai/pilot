/* Explicit account choices shared by Standard and MCP Android settings. */
(() => {
  const $ = id => document.getElementById(id);
  function update() {
    const mode = $('androidAccountMode').value;
    $('androidAccountCredentials').hidden = mode !== 'existing';
    $('androidTestUsername').required = mode === 'existing';
    $('androidTestPassword').required = mode === 'existing';
    if (mode !== 'existing') {
      $('androidTestUsername').value = '';
      $('androidTestPassword').value = '';
    }
    $('androidAccountHelp').textContent = mode === 'create'
      ? 'With test-build mode enabled, register one new account for this run and reuse it for login and protected checks. A new run gets a different account. Existing app data is preserved.'
      : mode === 'existing'
        ? 'Use the same supplied account throughout this run. No account is registered. Values stay private and are cleared after submission; existing app data is preserved.'
        : 'Public screens are tested without creating an account. Protected screens remain untested until you choose an account option.';
  }
  $('androidAccountMode').addEventListener('change', update);
  update();
})();
