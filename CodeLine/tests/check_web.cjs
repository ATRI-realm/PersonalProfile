// Exercise the script embedded in the page, including folder selection and rendering.
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

async function checkFolder(root) {
  const elements = new Map();
  function element() {
    return {
      children: [], textContent: '',
      append(child) { this.children.push(child); },
      replaceChildren() { this.children = []; },
      setAttribute() {}, removeAttribute() {},
      addEventListener(name, callback) { this[name] = callback; },
    };
  }
  const document = {
    getElementById(id) {
      if (!elements.has(id)) elements.set(id, element());
      return elements.get(id);
    },
    createElement: element,
  };
  const context = vm.createContext({ document, Intl, requestAnimationFrame: callback => callback() });
  const html = fs.readFileSync(path.join(__dirname, '..', '网页统计.html'), 'utf8');
  vm.runInContext(html.match(/<script>([\s\S]*?)<\/script>/)[1], context);
  const api = vm.runInContext('({fresh,scanCLike,scanPython,languages,isSkippedPath,languageFor})', context);
  const files = [];
  function walk(dir) {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      const absolute = path.join(dir, entry.name);
      const relative = path.basename(root) + '/' + path.relative(root, absolute).split(path.sep).join('/');
      if (entry.isDirectory()) {
        if (!api.isSkippedPath(relative + '/placeholder')) walk(absolute);
      } else if (entry.isFile()) {
        files.push({ name: entry.name, webkitRelativePath: relative, text: async () => fs.readFileSync(absolute, 'utf8') });
      }
    }
  }
  walk(root);
  document.getElementById('folderPicker').files = files;
  await document.getElementById('folderPicker').change();
  const rows = Object.fromEntries(document.getElementById('tableBody').children.map(row => {
    const cells = row.children.map(cell => cell.textContent);
    return [cells[0], cells.slice(1).map(value => Number(String(value).replaceAll(',', '')))];
  }));
  const details = [];
  for (const file of files) {
    const index = api.languageFor(file);
    if (index < 0) continue;
    const stats = api.fresh();
    (index === 3 ? api.scanPython : api.scanCLike)(await file.text(), stats);
    details.push({ file: file.webkitRelativePath, language: api.languages[index].name, ...stats });
  }
  return { rows, details, status: document.getElementById('status').textContent };
}

if (require.main === module) {
  checkFolder(path.resolve(process.argv[2])).then(result => process.stdout.write(JSON.stringify(result))).catch(error => {
    console.error(error); process.exitCode = 1;
  });
}
