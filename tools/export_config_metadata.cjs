// Export descriptions from the standalone helper without starting its UI.
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(__dirname, '..');
const html = fs.readFileSync(path.join(root, 'tools/config_editor.html'), 'utf8');
const source = html.match(/<script>([\s\S]*?)<\/script>/)[1];
const element = () => ({value:'',style:{},children:[],classList:{add(){},remove(){}},addEventListener(){},appendChild(){},setAttribute(){},querySelectorAll(){return [];}});
const context = vm.createContext({document:{getElementById:element,createElement:element,addEventListener(){},querySelectorAll(){return [];},querySelector(){return null;}},window:{location:{search:''}},URL,URLSearchParams,AbortController,Date,TypeError,setTimeout(){},clearTimeout(){}});
vm.runInContext(source, context);
const result = JSON.parse(vm.runInContext('JSON.stringify({schema:SCHEMA,sections:SECTIONS})', context));
let settingOrder = 0;
function visit(value, prefix='') {
  for (const [key, child] of Object.entries(value)) {
    const field = prefix ? `${prefix}.${key}` : key;
    const meta = context.metadataFor(field);
    if (child && typeof child === 'object' && !Array.isArray(child) && Object.keys(child).length && !meta.type?.startsWith('json')) visit(child, field);
    else result.schema[field] = {...meta, label:meta.label || context.labelFor(key), order:settingOrder++};
  }
}
visit(JSON.parse(fs.readFileSync(path.join(root, 'config.json'), 'utf8')));
const output = path.join(root, 'hudiy_dataview/static/configMetadata.json');
fs.mkdirSync(path.dirname(output), {recursive:true});
fs.writeFileSync(output, JSON.stringify(result, null, 2) + '\n');
