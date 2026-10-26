import { useEffect, useRef, useState } from 'react';
import { EditorContent, useEditor } from '@tiptap/react';
import StarterKit from '@tiptap/starter-kit';
import { Markdown } from '@tiptap/markdown';
import { Users, CalendarBlank, ChartBar, BookOpen, GearSix, CaretLeft, CaretRight, Plus, TextB, TextItalic, ListBullets, ListNumbers, Quotes, LinkSimple, ArrowUUpLeft, ArrowUUpRight, ArrowsOutSimple, ArrowsInSimple, Check, Eye, DownloadSimple } from '@phosphor-icons/react';

const today = () => {const d=new Date();return [d.getFullYear(),String(d.getMonth()+1).padStart(2,'0'),String(d.getDate()).padStart(2,'0')].join('-')};
const newMeeting = () => ({id:crypto.randomUUID(),goal:'',date:today(),time:'',format:'Онлайн',notes:''});
const formats = {'online':'Онлайн','in_person':'Очно','phone':'Телефон'};
const fromRecord = row => ({...row,format:formats[row.format]});
const extensions = () => [StarterKit.configure({heading:{levels:[1,2,3]},underline:false,strike:false,codeBlock:false,horizontalRule:false,link:{openOnClick:false}}),Markdown.configure({markedOptions:{gfm:false}})];
const dateLabel = date => new Date(date+'T12:00:00').toLocaleDateString('ru-RU',{day:'numeric',month:'long',year:'numeric'}).replace(' г.','');
function Tool({label,active,children,...props}) {return <button type="button" className={'tool '+(active?'active':'')} aria-label={label} title={label} aria-pressed={active} {...props}>{children}</button>}

function useDialog(active, close) {
 const callback=useRef(close);callback.current=close;
 useEffect(()=>{if(!active)return;const previous=document.activeElement;const dialog=document.querySelector('[role="dialog"]');
 const controls=()=>[...dialog.querySelectorAll('button:not(:disabled),input,a[href]')];controls()[0]?.focus();
 function key(e){if(e.key==='Escape'){e.preventDefault();callback.current()}if(e.key==='Tab'){const items=controls(),first=items[0],last=items.at(-1);if(e.shiftKey&&document.activeElement===first){e.preventDefault();last.focus()}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first.focus()}}}
 document.addEventListener('keydown',key);return()=>{document.removeEventListener('keydown',key);previous?.focus()};},[active]);
}

function Notes({value,onChange,mode,setMode,preview,setPreview}) {
 const [link,setLink]=useState(null);
 const sourceRef=useRef(null),visualPosition=useRef(1),sourcePosition=useRef([0,0]),switched=useRef(false);
 useDialog(link!==null,()=>setLink(null));
 const editor=useEditor({extensions:extensions(),content:value,contentType:'markdown',shouldRerenderOnTransaction:true,editorProps:{attributes:{'aria-label':'Содержание встречи',role:'textbox','aria-multiline':'true'}},onUpdate:({editor})=>onChange(editor.getMarkdown())});
 const viewer=useEditor({extensions:extensions(),content:value,contentType:'markdown',editable:false});
 useEffect(()=>{if(mode==='markdown'&&preview)viewer?.commands.setContent(value,{contentType:'markdown',emitUpdate:false})},[value,mode,preview,viewer]);
 function switchMode(next){if(next===mode)return;switched.current=true;if(mode==='visual')visualPosition.current=editor.state.selection.from;else if(sourceRef.current)sourcePosition.current=[sourceRef.current.selectionStart,sourceRef.current.selectionEnd];if(next==='visual')editor.commands.setContent(value,{contentType:'markdown',emitUpdate:false});setMode(next)}
 useEffect(()=>{if(!switched.current)return;if(mode==='markdown'&&sourceRef.current){sourceRef.current.focus();sourceRef.current.setSelectionRange(...sourcePosition.current)}else if(mode==='visual'&&editor)editor.chain().setTextSelection(Math.min(visualPosition.current,editor.state.doc.content.size)).focus().run()},[mode,editor]);
 function run(fn){fn(editor.chain().focus()).run()}
 return <><div className="editor-options"><div className="segmented" aria-label="Режим редактора"><button type="button" aria-pressed={mode==='visual'} className={mode==='visual'?'selected':''} onClick={()=>switchMode('visual')}>Визуально</button><button type="button" aria-pressed={mode==='markdown'} className={mode==='markdown'?'selected':''} onClick={()=>switchMode('markdown')}>Markdown</button></div>{mode==='markdown'&&<button type="button" className="quiet" aria-pressed={preview} onClick={()=>setPreview(!preview)}><Eye size={18}/> Предпросмотр</button>}</div>
 <div className="document">{mode==='visual'&&editor&&<div className="toolbar" role="toolbar" aria-label="Форматирование">
 <select aria-label="Стиль абзаца" value={[1,2,3].find(level=>editor.isActive('heading',{level}))||0} onChange={e=>run(c=>e.target.value==='0'?c.setParagraph():c.toggleHeading({level:Number(e.target.value)}))}><option value="0">Текст</option><option value="1">Заголовок 1</option><option value="2">Заголовок 2</option><option value="3">Заголовок 3</option></select><i/>
 <Tool label="Жирный (Ctrl+B)" active={editor.isActive('bold')} onClick={()=>run(c=>c.toggleBold())}><TextB/></Tool><Tool label="Курсив (Ctrl+I)" active={editor.isActive('italic')} onClick={()=>run(c=>c.toggleItalic())}><TextItalic/></Tool><i/>
 <Tool label="Маркированный список" active={editor.isActive('bulletList')} onClick={()=>run(c=>c.toggleBulletList())}><ListBullets/></Tool><Tool label="Нумерованный список" active={editor.isActive('orderedList')} onClick={()=>run(c=>c.toggleOrderedList())}><ListNumbers/></Tool><Tool label="Цитата" active={editor.isActive('blockquote')} onClick={()=>run(c=>c.toggleBlockquote())}><Quotes/></Tool><Tool label="Ссылка" active={editor.isActive('link')} onClick={()=>setLink(editor.getAttributes('link').href||'')}><LinkSimple/></Tool><i/>
 <Tool label="Отменить действие" disabled={!editor.can().undo()} onClick={()=>run(c=>c.undo())}><ArrowUUpLeft/></Tool><Tool label="Повторить действие" disabled={!editor.can().redo()} onClick={()=>run(c=>c.redo())}><ArrowUUpRight/></Tool></div>}
 {mode==='visual'?<EditorContent editor={editor}/>:<div className={'markdown-layout '+(preview?'with-preview':'')}><div className="source"><div className="pane-label">Markdown</div><textarea ref={sourceRef} aria-label="Исходный текст Markdown" spellCheck={false} value={value} onChange={e=>onChange(e.target.value)} placeholder="Запишите содержание встречи…"/></div>{preview&&<div className="preview"><div className="pane-label">Предпросмотр</div><EditorContent editor={viewer}/></div>}</div>}</div>
 <div className="hint">Заголовки, выделение, списки, цитаты и ссылки<span>Ctrl+S — сохранить</span></div>
 {link!==null&&<div className="shade"><form className="dialog" role="dialog" aria-modal="true" aria-labelledby="link-title" onSubmit={e=>{e.preventDefault();if(!link)run(c=>c.unsetLink());else if(/^(https?:\/\/|mailto:)/i.test(link))run(c=>c.extendMarkRange('link').setLink({href:link}));else return;setLink(null)}}><h2 id="link-title">Добавить ссылку</h2><label>Адрес<input autoFocus value={link} onChange={e=>setLink(e.target.value)} placeholder="https://example.com" pattern="(https?://|mailto:).*"/></label><div className="actions"><button type="button" className="secondary" onClick={()=>setLink(null)}>Отмена</button><button className="primary">Применить</button></div></form></div>}</>;
}

function Journal({initial,code,csrf,nonce:initialNonce}){
 const nonce=useRef(initialNonce),draftRef=useRef(null);
 const [meetings,setMeetings]=useState(initial),[draft,setDraft]=useState(initial[0]||newMeeting()),[mode,setMode]=useState('visual'),[preview,setPreview]=useState(false),[expanded,setExpanded]=useState(false),[collapsed,setCollapsed]=useState(false),[pending,setPending]=useState(null),[notice,setNotice]=useState(''),[error,setError]=useState(''),[editorKey,setEditorKey]=useState(0),[saving,setSaving]=useState(false);
 draftRef.current=draft;
 const saved=meetings.find(m=>m.id===draft.id),dirty=saved?JSON.stringify(saved)!==JSON.stringify(draft):!!(draft.goal||draft.notes||draft.time);
 useDialog(!!pending,()=>setPending(null));
 function update(key,value){setDraft(d=>({...d,[key]:value}));setNotice('');setError('')}
 function open(meeting){setDraft({...meeting});setEditorKey(k=>k+1);setNotice('');setError('')}
 function guard(action){if(dirty)setPending(()=>action);else action()}
 async function save(){
 if(saving)return false;
 if(!draft.goal.trim()){setError('Укажите цель встречи.');return false}
 const submitted={...draft};setSaving(true);setError('');
 try{
 const response=await fetch(location.pathname,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({operation:'meeting',code,csrf,nonce:nonce.current,meeting_id:saved?.id??null,revision:saved?.revision??null,meeting:{goal:submitted.goal,date:submitted.date,time:submitted.time,format:Object.keys(formats).find(k=>formats[k]===submitted.format),notes:submitted.notes}})});
 const result=await response.json();if(result.nonce)nonce.current=result.nonce;
 if(!response.ok)throw new Error(result.error||'Запись не сохранена.');
 const stored=fromRecord(result.meeting);
 setMeetings(ms=>[...ms.filter(m=>m.id!==submitted.id),stored].sort((a,b)=>(b.date+b.time).localeCompare(a.date+a.time)||b.id-a.id));
 const unchanged=JSON.stringify(draftRef.current)===JSON.stringify(submitted);
 if(unchanged)setDraft(stored);
 setNotice('Изменения сохранены');return unchanged?stored:false;
 }catch(error){setError(error.message==='Failed to fetch'?'Нет связи с локальной базой. Изменения не сохранены.':error.message);return false}
 finally{setSaving(false)}
 }
 function create(){guard(()=>open(newMeeting()))}
 function cancel(){if(dirty)setPending(()=>stored=>open(stored||saved||meetings[0]||newMeeting()))}
 function download(){const url=URL.createObjectURL(new Blob([draft.notes],{type:'text/markdown;charset=utf-8'}));const a=document.createElement('a');a.href=url;a.download='meeting-'+draft.date+'.md';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)}
 useEffect(()=>{function before(e){if(dirty){e.preventDefault();e.returnValue=''}}window.addEventListener('beforeunload',before);return()=>window.removeEventListener('beforeunload',before)},[dirty]);
 useEffect(()=>{function key(e){if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='s'){e.preventDefault();save()}}window.addEventListener('keydown',key);return()=>window.removeEventListener('keydown',key)});
 const month=date=>new Date(date+'T12:00:00').toLocaleDateString('ru-RU',{month:'long',year:'numeric'}).replace(' г.','');
 return <div className={'app '+(collapsed?'collapsed':'')}><aside><div className="brand"><b>okama</b><span>Planner</span></div><nav aria-label="Основная навигация"><button className="nav current"><Users weight="fill"/><span>Клиенты</span></button>{[[CalendarBlank,'Календарь'],[ChartBar,'Аналитика'],[BookOpen,'База знаний'],[GearSix,'Настройки']].map(([Icon,title])=><button disabled title="Раздел вне этого макета" className="nav" key={title}><Icon/><span>{title}</span></button>)}</nav><button className="collapse" onClick={()=>setCollapsed(!collapsed)} aria-label="Свернуть или раскрыть меню"><CaretLeft/><span>Свернуть</span></button></aside>
 <main><div className="breadcrumb"><a href={location.pathname}>Клиенты</a> <span>/</span> {code} <small>Локальная база Planner</small></div><h1>Карточка клиента</h1><div className="tabs"><a href={location.pathname+'?code='+encodeURIComponent(code)}>Анкета</a><a href={location.pathname+'?view=plan&code='+encodeURIComponent(code)}>Финансовые планы</a><button className="active" aria-current="page">Журнал встреч</button></div><header><h2>Журнал встреч</h2><button className="primary" onClick={create}><Plus/>Новая встреча</button></header>
 <div className={'workspace '+(expanded?'expanded':'')}>{!expanded&&<section className="meeting-list" aria-label="Встречи клиента">{meetings.map((m,i)=><div key={m.id}>{(!i||month(m.date)!==month(meetings[i-1].date))&&<h3 className="month">{month(m.date)}</h3>}<button className={'meeting '+(m.id===draft.id?'selected':'')} aria-current={m.id===draft.id?'true':undefined} onClick={()=>{if(!saving&&m.id!==draft.id)guard(()=>open(m))}}><div><b>{dateLabel(m.date)}{m.time&&', '+m.time}</b><span>{m.goal}</span></div><CaretRight/></button></div>)}{!saved&&<p className="new-label">Новая встреча · не сохранена</p>}</section>}
 <section className="meeting-editor" aria-label="Редактирование встречи"><div className="purpose"><label>Цель встречи<input aria-label="Цель встречи" value={draft.goal} onChange={e=>update('goal',e.target.value)} placeholder="Например, обсуждение целей" required/></label><Tool label={expanded?'Показать список встреч':'Развернуть редактор'} onClick={()=>setExpanded(!expanded)}>{expanded?<ArrowsInSimple/>:<ArrowsOutSimple/>}</Tool></div>
 <div className="metadata"><label>Дата<input aria-label="Дата встречи" placeholder="ДД.ММ.ГГГГ" required value={draft.date.split('-').reverse().join('.')} onChange={e=>update('date',e.target.value.split('.').reverse().join('-'))}/></label><label>Время <small>необязательно</small><input aria-label="Время встречи" placeholder="ЧЧ:ММ" value={draft.time} onChange={e=>update('time',e.target.value)}/></label><label>Формат<select aria-label="Формат встречи" value={draft.format} onChange={e=>update('format',e.target.value)}><option>Онлайн</option><option>Очно</option><option>Телефон</option></select></label></div>
 <div className="content-heading"><h3>Содержание встречи</h3><Tool label="Скачать Markdown" onClick={download}><DownloadSimple/></Tool></div><Notes key={editorKey} value={draft.notes} onChange={v=>update('notes',v)} mode={mode} setMode={setMode} preview={preview} setPreview={setPreview}/>
 <footer><div role="status" aria-live="polite" className={'status '+(error?'error':dirty?'dirty':'')}>{!dirty&&!error&&<Check/>}<span>{error||(dirty?'Есть несохранённые изменения':notice||'Все изменения сохранены')}</span></div><button className="secondary" disabled={!dirty||saving} onClick={cancel}>Отмена</button><button className="primary" disabled={!dirty||saving} onClick={save}>Сохранить</button></footer></section></div><p className="demo">Данные сохраняются в локальной базе Planner. Содержание встреч не передаётся ИИ при выключенном персональном доступе.</p></main>
 {pending&&<div className="shade"><section className="dialog" role="dialog" aria-modal="true" aria-labelledby="unsaved-title"><h2 id="unsaved-title">Сохранить изменения?</h2><p>В записи встречи есть несохранённые изменения.</p><div className="actions"><button autoFocus className="quiet" onClick={()=>setPending(null)}>Остаться</button><button className="secondary" onClick={()=>{pending(false);setPending(null)}}>Не сохранять</button><button className="primary" onClick={async()=>{const stored=await save();if(stored){pending(stored);setPending(null)}}}>Сохранить и перейти</button></div></section></div>}</div>
}

export function App(){
 const [context,setContext]=useState(null),[error,setError]=useState('');
 useEffect(()=>{const controller=new AbortController();const code=document.getElementById('root').dataset.code;
 fetch(location.pathname+'?api=meetings&code='+encodeURIComponent(code),{signal:controller.signal}).then(async response=>{if(!response.ok)throw new Error('Не удалось открыть дневник клиента.');return response.json()}).then(setContext).catch(error=>{if(error.name!=='AbortError')setError(error.message)});return()=>controller.abort()},[]);
 if(error)return <div role="alert" className="editor-error">{error} <button onClick={()=>location.reload()}>Повторить</button></div>;
 if(!context)return <p role="status" className="editor-error">Открываем дневник…</p>;
 return <Journal initial={context.meetings.map(fromRecord)} code={context.code} csrf={context.csrf} nonce={context.nonce}/>;
}
