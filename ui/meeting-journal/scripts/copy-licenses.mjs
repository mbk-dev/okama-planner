import {readFileSync,writeFileSync,readdirSync} from 'node:fs';
import {createRequire} from 'node:module';
import {dirname,join,resolve} from 'node:path';
const require=createRequire(import.meta.url),parts=[];
for(const name of ['react','react-dom','@tiptap/core','@tiptap/react','@tiptap/markdown','@tiptap/starter-kit','@phosphor-icons/react']){
 let root=dirname(require.resolve(name));
 for(let i=0;i<5;i++,root=dirname(root)){
  const license=readdirSync(root).find(x=>/^licen[sc]e(\.md|\.txt)?$/i.test(x));
  if(license){parts.push(name+'\n'+readFileSync(join(root,license),'utf8'));break;}
 }
}
writeFileSync(resolve('../../src/okama_planner/_journal_assets/NOTICE.txt'),parts.join('\n\n---\n\n'));
