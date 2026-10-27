import { useEffect, useRef, useState } from 'react';
import { EditorContent, useEditor } from '@tiptap/react';
import StarterKit from '@tiptap/starter-kit';
import { Markdown } from '@tiptap/markdown';
import { Users, CalendarBlank, ChartBar, BookOpen, GearSix, CaretLeft, CaretRight, Plus, TextB, TextItalic, ListBullets, ListNumbers, Quotes, LinkSimple, ArrowUUpLeft, ArrowUUpRight, ArrowsOutSimple, ArrowsInSimple, Check, Eye, DownloadSimple } from '@phosphor-icons/react';

const root = document.getElementById('root');
const STRINGS = JSON.parse(root.dataset.strings || '{}');
const LOCALE = root.dataset.locale || 'en-US';
const t = (key, values) => {
  let text = key in STRINGS ? STRINGS[key] : key;
  if (values) for (const [name, value] of Object.entries(values)) text = text.replace('{' + name + '}', value);
  return text;
};

const today = () => {const d=new Date();return [d.getFullYear(),String(d.getMonth()+1).padStart(2,'0'),String(d.getDate()).padStart(2,'0')].join('-')};
const newMeeting = () => ({id:crypto.randomUUID(),goal:'',date:today(),time:'',format:'online',notes:''});
const formats = ['online','in_person','phone'];
const formatLabel = value => t('ui_format_' + (value === 'in_person' ? 'in_person' : value));
const fromRecord = row => ({...row,format:formats.includes(row.format) ? row.format : 'online'});
const extensions = () => [StarterKit.configure({heading:{levels:[1,2,3]},underline:false,strike:false,codeBlock:false,horizontalRule:false,link:{openOnClick:false}}),Markdown.configure({markedOptions:{gfm:false}})];
const dateLabel = date => new Date(date+'T12:00:00').toLocaleDateString(LOCALE,{day:'numeric',month:'long',year:'numeric'});
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
 const editor=useEditor({extensions:extensions(),content:value,contentType:'markdown',shouldRerenderOnTransaction:true,editorProps:{attributes:{'aria-label':t('ui_meeting_content'),role:'textbox','aria-multiline':'true'}},onUpdate:({editor})=>onChange(editor.getMarkdown())});
 const viewer=useEditor({extensions:extensions(),content:value,contentType:'markdown',editable:false});
 useEffect(()=>{if(mode==='markdown'&&preview)viewer?.commands.setContent(value,{contentType:'markdown',emitUpdate:false})},[value,mode,preview,viewer]);
 function switchMode(next){if(next===mode)return;switched.current=true;if(mode==='visual')visualPosition.current=editor.state.selection.from;else if(sourceRef.current)sourcePosition.current=[sourceRef.current.selectionStart,sourceRef.current.selectionEnd];if(next==='visual')editor.commands.setContent(value,{contentType:'markdown',emitUpdate:false});setMode(next)}
 useEffect(()=>{if(!switched.current)return;if(mode==='markdown'&&sourceRef.current){sourceRef.current.focus();sourceRef.current.setSelectionRange(...sourcePosition.current)}else if(mode==='visual'&&editor)editor.chain().setTextSelection(Math.min(visualPosition.current,editor.state.doc.content.size)).focus().run()},[mode,editor]);
 function run(fn){fn(editor.chain().focus()).run()}
 return <><div className="editor-options"><div className="segmented" aria-label={t('ui_editor_mode')}><button type="button" aria-pressed={mode==='visual'} className={mode==='visual'?'selected':''} onClick={()=>switchMode('visual')}>{t('ui_visual')}</button><button type="button" aria-pressed={mode==='markdown'} className={mode==='markdown'?'selected':''} onClick={()=>switchMode('markdown')}>Markdown</button></div>{mode==='markdown'&&<button type="button" className="quiet" aria-pressed={preview} onClick={()=>setPreview(!preview)}><Eye size={18}/> {t('ui_preview')}</button>}</div>
 <div className="document">{mode==='visual'&&editor&&<div className="toolbar" role="toolbar" aria-label={t('ui_formatting')}>
 <select aria-label={t('ui_paragraph_style')} value={[1,2,3].find(level=>editor.isActive('heading',{level}))||0} onChange={e=>run(c=>e.target.value==='0'?c.setParagraph():c.toggleHeading({level:Number(e.target.value)}))}><option value="0">{t('ui_text_style')}</option><option value="1">{t('ui_heading1')}</option><option value="2">{t('ui_heading2')}</option><option value="3">{t('ui_heading3')}</option></select><i/>
 <Tool label={t('ui_bold')} active={editor.isActive('bold')} onClick={()=>run(c=>c.toggleBold())}><TextB/></Tool><Tool label={t('ui_italic')} active={editor.isActive('italic')} onClick={()=>run(c=>c.toggleItalic())}><TextItalic/></Tool><i/>
 <Tool label={t('ui_bullet_list')} active={editor.isActive('bulletList')} onClick={()=>run(c=>c.toggleBulletList())}><ListBullets/></Tool><Tool label={t('ui_numbered_list')} active={editor.isActive('orderedList')} onClick={()=>run(c=>c.toggleOrderedList())}><ListNumbers/></Tool><Tool label={t('ui_quote')} active={editor.isActive('blockquote')} onClick={()=>run(c=>c.toggleBlockquote())}><Quotes/></Tool><Tool label={t('ui_link')} active={editor.isActive('link')} onClick={()=>setLink(editor.getAttributes('link').href||'')}><LinkSimple/></Tool><i/>
 <Tool label={t('ui_undo')} disabled={!editor.can().undo()} onClick={()=>run(c=>c.undo())}><ArrowUUpLeft/></Tool><Tool label={t('ui_redo')} disabled={!editor.can().redo()} onClick={()=>run(c=>c.redo())}><ArrowUUpRight/></Tool></div>}
 {mode==='visual'?<EditorContent editor={editor}/>:<div className={'markdown-layout '+(preview?'with-preview':'')}><div className="source"><div className="pane-label">Markdown</div><textarea ref={sourceRef} aria-label={t('ui_markdown_source')} spellCheck={false} value={value} onChange={e=>onChange(e.target.value)} placeholder={t('ui_write_content')}/></div>{preview&&<div className="preview"><div className="pane-label">{t('ui_preview')}</div><EditorContent editor={viewer}/></div>}</div>}</div>
 <div className="hint">{t('ui_editor_hint')}<span>{t('ui_save_shortcut')}</span></div>
 {link!==null&&<div className="shade"><form className="dialog" role="dialog" aria-modal="true" aria-labelledby="link-title" onSubmit={e=>{e.preventDefault();if(!link)run(c=>c.unsetLink());else if(/^(https?:\/\/|mailto:)/i.test(link))run(c=>c.extendMarkRange('link').setLink({href:link}));else return;setLink(null)}}><h2 id="link-title">{t('ui_add_link')}</h2><label>{t('ui_address')}<input autoFocus value={link} onChange={e=>setLink(e.target.value)} placeholder="https://example.com" pattern="(https?://|mailto:).*"/></label><div className="actions"><button type="button" className="secondary" onClick={()=>setLink(null)}>{t('ui_cancel')}</button><button className="primary">{t('ui_apply')}</button></div></form></div>}</>;
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
 if(!draft.goal.trim()){setError(t('ui_goal_required'));return false}
 const submitted={...draft};setSaving(true);setError('');
 try{
 const response=await fetch(location.pathname,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({operation:'meeting',code,csrf,nonce:nonce.current,meeting_id:saved?.id??null,revision:saved?.revision??null,meeting:{goal:submitted.goal,date:submitted.date,time:submitted.time,format:submitted.format,notes:submitted.notes}})});
 const result=await response.json();if(result.nonce)nonce.current=result.nonce;
 if(!response.ok)throw new Error(result.error||t('ui_record_not_saved'));
 const stored=fromRecord(result.meeting);
 setMeetings(ms=>[...ms.filter(m=>m.id!==submitted.id),stored].sort((a,b)=>(b.date+b.time).localeCompare(a.date+a.time)||b.id-a.id));
 const unchanged=JSON.stringify(draftRef.current)===JSON.stringify(submitted);
 if(unchanged)setDraft(stored);
 setNotice(t('ui_changes_saved'));return unchanged?stored:false;
 }catch(error){setError(error.message==='Failed to fetch'?t('ui_no_connection'):error.message);return false}
 finally{setSaving(false)}
 }
 function create(){guard(()=>open(newMeeting()))}
 function cancel(){if(dirty)setPending(()=>stored=>open(stored||saved||meetings[0]||newMeeting()))}
 function download(){const url=URL.createObjectURL(new Blob([draft.notes],{type:'text/markdown;charset=utf-8'}));const a=document.createElement('a');a.href=url;a.download='meeting-'+draft.date+'.md';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)}
 useEffect(()=>{function before(e){if(dirty){e.preventDefault();e.returnValue=''}}window.addEventListener('beforeunload',before);return()=>window.removeEventListener('beforeunload',before)},[dirty]);
 useEffect(()=>{function key(e){if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='s'){e.preventDefault();save()}}window.addEventListener('keydown',key);return()=>window.removeEventListener('keydown',key)});
 const month=date=>new Date(date+'T12:00:00').toLocaleDateString(LOCALE,{month:'long',year:'numeric'});
 return <div className={'app '+(collapsed?'collapsed':'')}><aside><div className="brand"><b>okama</b><span>Planner</span></div><nav aria-label={t('ui_nav_clients')}><button className="nav current"><Users weight="fill"/><span>{t('ui_nav_clients')}</span></button>{[[CalendarBlank,'ui_nav_calendar'],[ChartBar,'ui_nav_analytics'],[BookOpen,'ui_nav_knowledge'],[GearSix,'ui_nav_settings']].map(([Icon,key])=><button disabled title={t('ui_section_unavailable')} className="nav" key={key}><Icon/><span>{t(key)}</span></button>)}</nav><button className="collapse" onClick={()=>setCollapsed(!collapsed)} aria-label={t('ui_collapse_aria')}><CaretLeft/><span>{t('ui_collapse')}</span></button></aside>
 <main><div className="breadcrumb"><a href={location.pathname}>{t('ui_nav_clients')}</a> <span>/</span> {code} <small>{t('ui_local_database')}</small></div><h1>{t('ui_client_card')}</h1><div className="tabs"><a href={location.pathname+'?code='+encodeURIComponent(code)}>{t('ui_profile')}</a><a href={location.pathname+'?view=plan&code='+encodeURIComponent(code)}>{t('ui_financial_plans')}</a><button className="active" aria-current="page">{t('ui_meeting_journal')}</button></div><header><h2>{t('ui_meeting_journal')}</h2><button className="primary" onClick={create}><Plus/>{t('ui_new_meeting')}</button></header>
 <div className={'workspace '+(expanded?'expanded':'')}>{!expanded&&<section className="meeting-list" aria-label={t('ui_client_meetings')}>{meetings.map((m,i)=><div key={m.id}>{(!i||month(m.date)!==month(meetings[i-1].date))&&<h3 className="month">{month(m.date)}</h3>}<button className={'meeting '+(m.id===draft.id?'selected':'')} aria-current={m.id===draft.id?'true':undefined} onClick={()=>{if(!saving&&m.id!==draft.id)guard(()=>open(m))}}><div><b>{dateLabel(m.date)}{m.time&&', '+m.time}</b><span>{m.goal}</span></div><CaretRight/></button></div>)}{!saved&&<p className="new-label">{t('ui_new_meeting_unsaved')}</p>}</section>}
 <section className="meeting-editor" aria-label={t('ui_meeting_content')}><div className="purpose"><label>{t('ui_meeting_goal')}<input aria-label={t('ui_meeting_goal')} value={draft.goal} onChange={e=>update('goal',e.target.value)} placeholder={t('ui_goal_placeholder')} required/></label><Tool label={expanded?t('ui_show_meeting_list'):t('ui_expand_editor')} onClick={()=>setExpanded(!expanded)}>{expanded?<ArrowsInSimple/>:<ArrowsOutSimple/>}</Tool></div>
 <div className="metadata"><label>{t('ui_date')}<input type="date" aria-label={t('ui_date')} required value={draft.date} onChange={e=>update('date',e.target.value)}/></label><label>{t('ui_time')} <small>{t('ui_optional')}</small><input aria-label={t('ui_time')} placeholder={t('ui_time_placeholder')} value={draft.time} onChange={e=>update('time',e.target.value)}/></label><label>{t('ui_format')}<select aria-label={t('ui_format')} value={draft.format} onChange={e=>update('format',e.target.value)}>{formats.map(value=><option key={value} value={value}>{formatLabel(value)}</option>)}</select></label></div>
 <div className="content-heading"><h3>{t('ui_meeting_content')}</h3><Tool label={t('ui_download_markdown')} onClick={download}><DownloadSimple/></Tool></div><Notes key={editorKey} value={draft.notes} onChange={v=>update('notes',v)} mode={mode} setMode={setMode} preview={preview} setPreview={setPreview}/>
 <footer><div role="status" aria-live="polite" className={'status '+(error?'error':dirty?'dirty':'')}>{!dirty&&!error&&<Check/>}<span>{error||(dirty?t('ui_unsaved_changes'):notice||t('ui_all_saved'))}</span></div><button className="secondary" disabled={!dirty||saving} onClick={cancel}>{t('ui_cancel')}</button><button className="primary" disabled={!dirty||saving} onClick={save}>{t('ui_save')}</button></footer></section></div><p className="demo">{t('ui_journal_notice')}</p></main>
 {pending&&<div className="shade"><section className="dialog" role="dialog" aria-modal="true" aria-labelledby="unsaved-title"><h2 id="unsaved-title">{t('ui_save_changes_q')}</h2><p>{t('ui_unsaved_body')}</p><div className="actions"><button autoFocus className="quiet" onClick={()=>setPending(null)}>{t('ui_stay')}</button><button className="secondary" onClick={()=>{pending(false);setPending(null)}}>{t('ui_do_not_save')}</button><button className="primary" onClick={async()=>{const stored=await save();if(stored){pending(stored);setPending(null)}}}>{t('ui_save_and_continue')}</button></div></section></div>}</div>
}

export function App(){
 const [context,setContext]=useState(null),[error,setError]=useState('');
 useEffect(()=>{const controller=new AbortController();const code=document.getElementById('root').dataset.code;
 fetch(location.pathname+'?api=meetings&code='+encodeURIComponent(code),{signal:controller.signal}).then(async response=>{if(!response.ok)throw new Error(t('ui_open_journal_failed'));return response.json()}).then(setContext).catch(error=>{if(error.name!=='AbortError')setError(error.message)});return()=>controller.abort()},[]);
 if(error)return <div role="alert" className="editor-error">{error} <button onClick={()=>location.reload()}>{t('ui_retry')}</button></div>;
 if(!context)return <p role="status" className="editor-error">{t('ui_opening_journal')}</p>;
 return <Journal initial={context.meetings.map(fromRecord)} code={context.code} csrf={context.csrf} nonce={context.nonce}/>;
}
