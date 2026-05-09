const e = require('electron');
process.stderr.write('type: ' + typeof e + '\n');
process.stderr.write('is_electron: ' + !!(process.versions && process.versions.electron) + '\n');
process.stderr.write('process.type: ' + (process.type || 'undefined') + '\n');
if (typeof e === 'object' && e.app) {
  process.stderr.write('SUCCESS\n');
  e.app.quit();
} else {
  process.stderr.write('FAIL - e value: ' + String(e).substring(0, 80) + '\n');
  process.exit(1);
}
