import { useEffect, useState, type FormEvent } from 'react';
import { AsyncFeedback } from '../../AsyncFeedback';
import { ScreenTitle } from '../../ScreenTitle';
import { formatDateTime, showNumber } from '../../format';
import { AlertDialog, Button, ContentButton, SearchInput, Select, Tag, TextArea, TextInput } from '../../ui';
import { useAuth } from '../../auth/AuthProvider';
import { useWorkspaceNav } from '../../workspace/navContext';
import { adminApi } from '../adminApi';
import './board.css';

export const meta = { code: 'SYS0009', title: '게시판', icon: 'document', keywords: ['게시판', '공지', '공지사항', '게시글', '알림', '안내', '자유', '댓글'] };

type Kind = 'NOTICE' | 'GENERAL';
type Summary = { id: number; type: Kind; title: string; pinned: boolean; published: boolean; createdBy: string; writer: string; createdAt: string; views: number; comments: number };
type Comment = { id: number; body: string; createdBy: string; writer: string; createdAt: string };
type Post = Summary & { body: string; commentList: Comment[]; previous: { id: number; title: string } | null; next: { id: number; title: string } | null };
type Page = { total: number; page: number; size: number; items: Summary[] };
type Draft = { id: number | null; type: Kind; title: string; body: string; pinned: boolean; published: boolean };
const SIZE = 20, DAY = 24 * 60 * 60 * 1000;
const asDate = (value: string) => new Date(/[zZ]$/.test(value) ? value : value.replace(' ', 'T') + 'Z');
// Today's posts show the time, older ones the date, the way boards usually do.
const shortDate = (value: string) => { const full = formatDateTime(value); return full.slice(0, 10) === formatDateTime(new Date().toISOString()).slice(0, 10) ? full.slice(11) : full.slice(0, 10); };
const isNew = (value: string) => Date.now() - asDate(value).getTime() < DAY;

/**
 * The board, laid out like a community board: a numbered list (notices on top) with comment counts, writer, date and
 * views, paging and search below it; a post page with comments and previous/next; a writing page. Everyone writes
 * general posts and comments and manages their own; administrators write notices, pin or hide posts and manage all.
 */
export default function Board() {
  const user = useAuth().user;
  const admin = Boolean(user?.admin);
  const intent = useWorkspaceNav()?.intents[meta.code];
  const [mode, setMode] = useState<'list' | 'read' | 'write'>('list');
  const [list, setList] = useState<Page>({ total: 0, page: 1, size: SIZE, items: [] });
  const [filter, setFilter] = useState({ type: '', field: 'title', keyword: '' });
  const [typed, setTyped] = useState({ field: 'title', keyword: '' });
  const [post, setPost] = useState<Post | null>(null);
  const [draft, setDraft] = useState<Draft>({ id: null, type: 'GENERAL', title: '', body: '', pinned: false, published: true });
  const [comment, setComment] = useState('');
  const [error, setError] = useState('');
  const [confirm, setConfirm] = useState<{ what: 'post' } | { what: 'comment'; id: number } | null>(null);
  const run = (work: () => Promise<void>) => { setError(''); void work().catch(cause => setError(cause instanceof Error ? cause.message : '처리하지 못했습니다.')); };

  async function load(page = list.page, next = filter) {
    setFilter(next);
    const query = new URLSearchParams({ type: next.type, field: next.field, keyword: next.keyword, page: String(page), size: String(SIZE) });
    setList(await adminApi<Page>(`/api/auth/posts?${query}`));
  }
  async function read(id: number, count = true) {
    setPost(await adminApi<Post>(`/api/auth/posts/${id}${count ? '' : '?count=false'}`));
    setComment(''); setMode('read');
  }
  // First open lists the posts; opened from the home page ticker it goes straight to that post.
  useEffect(() => {
    const id = Number(intent?.values.post);
    run(async () => { await load(1); if (id) await read(id); else setMode('list'); });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [intent?.at]);
  const toList = () => run(async () => { await load(); setMode('list'); });
  const write = (from?: Post) => { setDraft(from ? { id: from.id, type: from.type, title: from.title, body: from.body, pinned: from.pinned, published: from.published }
    : { id: null, type: 'GENERAL', title: '', body: '', pinned: false, published: true }); setError(''); setMode('write'); };
  function submit(event: FormEvent) {
    event.preventDefault();
    run(async () => {
      const body = { type: draft.type, title: draft.title, body: draft.body, pinned: draft.pinned, published: draft.published };
      const saved = draft.id === null ? await adminApi<{ id: number }>('/api/auth/posts', 'POST', body) : await adminApi<{ id: number }>(`/api/auth/posts/${draft.id}`, 'PUT', body);
      await load(draft.id === null ? 1 : list.page);
      await read(saved.id, false);
    });
  }
  const mine = (owner: string) => admin || owner === user?.username;
  const pages = Math.max(1, Math.ceil(list.total / SIZE));
  const first = Math.max(1, Math.min(list.page - 4, pages - 9)), numbers = Array.from({ length: Math.min(10, pages) }, (_, index) => first + index);
  const numberOf = (item: Summary) => list.total - (list.page - 1) * SIZE - list.items.indexOf(item);

  return <div className="board" data-ui="board" data-mode={mode}>
    <div className="board-head">
      <ScreenTitle>게시판</ScreenTitle>
      {mode === 'list' && <div className="board-kinds" role="group" aria-label="구분">
        {[['', '전체'], ['NOTICE', '공지'], ['GENERAL', '일반']].map(([value, label]) => <Button key={value} label={label} size="sm" variant="ghost" aria-pressed={filter.type === value}
          isActive={filter.type === value} onClick={() => run(() => load(1, { ...filter, type: value }))} />)}
      </div>}
      <span className="board-total">{mode === 'list' ? `전체 ${showNumber(list.total)}건` : ''}</span>
    </div>
    <AsyncFeedback error={error} />

    {mode === 'list' && <>
      <div className="board-dock"><table className="board-list bp6-html-table bp6-compact bp6-interactive" aria-label="게시글 목록">
        <thead><tr><th className="col-no">번호</th><th>제목</th><th className="col-writer">글쓴이</th><th className="col-date">날짜</th><th className="col-views">조회</th></tr></thead>
        <tbody>
          {list.items.map(item => {
            const notice = item.type === 'NOTICE' || item.pinned;
            return <tr key={item.id} className={notice ? 'is-notice' : undefined} data-post={item.id}>
              <td className="col-no">{notice ? <Tag intent="danger" minimal>공지</Tag> : numberOf(item)}</td>
              <td className="col-title"><ContentButton className="board-link" onClick={() => run(() => read(item.id))}>
                {!item.published && <span className="board-hidden">[숨김] </span>}<span className="board-subject">{item.title}</span>
                {item.comments > 0 && <span className="board-count" aria-label={`댓글 ${item.comments}개`}>[{item.comments}]</span>}
                {isNew(item.createdAt) && <span className="board-new" aria-label="새 글">N</span>}
              </ContentButton></td>
              <td className="col-writer">{item.writer}</td><td className="col-date">{shortDate(item.createdAt)}</td><td className="col-views">{showNumber(item.views)}</td>
            </tr>;
          })}
          {list.items.length === 0 && <tr><td colSpan={5} className="board-empty">{filter.keyword ? '찾는 글이 없습니다.' : '아직 글이 없습니다. 첫 글을 남겨 보세요.'}</td></tr>}
        </tbody>
      </table></div>
      <div className="board-foot">
        <span />
        <nav className="board-pages" aria-label="페이지">
          <Button label="처음" icon="double-chevron-left" isIconOnly variant="ghost" size="sm" isDisabled={list.page <= 1} onClick={() => run(() => load(1))} />
          <Button label="이전" icon="chevron-left" isIconOnly variant="ghost" size="sm" isDisabled={list.page <= 1} onClick={() => run(() => load(list.page - 1))} />
          {numbers.map(number => <Button key={number} label={String(number)} size="sm" variant={number === list.page ? 'primary' : 'ghost'} aria-current={number === list.page ? 'page' : undefined}
            onClick={() => run(() => load(number))} />)}
          <Button label="다음" icon="chevron-right" isIconOnly variant="ghost" size="sm" isDisabled={list.page >= pages} onClick={() => run(() => load(list.page + 1))} />
          <Button label="끝" icon="double-chevron-right" isIconOnly variant="ghost" size="sm" isDisabled={list.page >= pages} onClick={() => run(() => load(pages))} />
        </nav>
        <Button label="글쓰기" variant="primary" icon="edit" onClick={() => write()} />
      </div>
      <form className="board-search" role="search" onSubmit={event => { event.preventDefault(); run(() => load(1, { ...filter, ...typed })); }}>
        <div style={{ width: 96 }}><Select label="검색 대상" hideLabel value={typed.field} onChange={value => setTyped(previous => ({ ...previous, field: value }))}
          options={[{ value: 'title', label: '제목' }, { value: 'body', label: '내용' }, { value: 'writer', label: '글쓴이' }]} /></div>
        <div className="board-search-input"><SearchInput label="검색어" placeholder="검색어" value={typed.keyword} onChange={keyword => setTyped(previous => ({ ...previous, keyword }))} /></div>
        <Button type="submit" label="검색" icon="search" />
        {filter.keyword && <Button label="검색 해제" variant="ghost" onClick={() => { setTyped({ field: 'title', keyword: '' }); run(() => load(1, { ...filter, field: 'title', keyword: '' })); }} />}
      </form>
    </>}

    {mode === 'read' && post && <article className="board-post" aria-label={post.title}>
      <header>
        <h2>{post.type === 'NOTICE' && <Tag intent="danger" minimal>공지</Tag>} {!post.published && <span className="board-hidden">[숨김] </span>}{post.title}</h2>
        <div className="board-meta"><strong>{post.writer}</strong><span>{formatDateTime(post.createdAt)}</span><span>조회 {showNumber(post.views)}</span><span>댓글 {post.commentList.length}</span></div>
      </header>
      <div className="board-body">{post.body || <span className="board-muted">내용이 없습니다.</span>}</div>
      <div className="board-actions">
        <Button label="목록" icon="list" onClick={toList} />
        <span style={{ flex: 1 }} />
        {mine(post.createdBy) && <><Button label="수정" icon="edit" onClick={() => write(post)} />
          <Button label="삭제" icon="trash" variant="destructive" outlined onClick={() => setConfirm({ what: 'post' })} /></>}
        <Button label="글쓰기" variant="primary" icon="edit" onClick={() => write()} />
      </div>
      <section className="board-comments" aria-label="댓글">
        <h3>댓글 <em>{post.commentList.length}</em></h3>
        <ul>{post.commentList.map(item => <li key={item.id}>
          <div className="board-comment-head"><strong>{item.writer}</strong><span>{formatDateTime(item.createdAt)}</span>
            {mine(item.createdBy) && <Button label="삭제" size="sm" variant="ghost" onClick={() => setConfirm({ what: 'comment', id: item.id })} />}</div>
          <p>{item.body}</p>
        </li>)}</ul>
        {post.commentList.length === 0 && <p className="board-muted">첫 댓글을 남겨 보세요.</p>}
        <form className="board-comment-form" onSubmit={event => { event.preventDefault(); run(async () => {
          const commentList = await adminApi<Comment[]>(`/api/auth/posts/${post.id}/comments`, 'POST', { body: comment });
          setPost({ ...post, commentList }); setComment('');
        }); }}>
          <TextArea label="댓글 내용" hideLabel rows={3} maxLength={2000} placeholder="댓글을 남겨 보세요" value={comment} onChange={setComment} />
          <Button type="submit" label="등록" variant="primary" isDisabled={!comment.trim()} />
        </form>
      </section>
      <nav className="board-neighbours" aria-label="이전글 다음글">
        {post.next && <ContentButton onClick={() => run(() => read(post.next!.id))}><span>다음글</span>{post.next.title}</ContentButton>}
        {post.previous && <ContentButton onClick={() => run(() => read(post.previous!.id))}><span>이전글</span>{post.previous.title}</ContentButton>}
      </nav>
    </article>}

    {mode === 'write' && <form className="board-write" aria-label={draft.id === null ? '글쓰기' : '글 수정'} onSubmit={submit}>
      <h2>{draft.id === null ? '글쓰기' : '글 수정'}</h2>
      <div className="board-write-row">
        {admin && <div style={{ width: 150 }}><Select label="구분" value={draft.type} onChange={value => setDraft(previous => ({ ...previous, type: value === 'NOTICE' ? 'NOTICE' : 'GENERAL' }))}
          options={[{ value: 'GENERAL', label: '일반' }, { value: 'NOTICE', label: '공지 (홈에 표시)' }]} /></div>}
        <div style={{ flex: 1, minWidth: 240 }}><TextInput label="제목" isRequired value={draft.title} onChange={value => setDraft(previous => ({ ...previous, title: value }))} /></div>
        {admin && <div style={{ width: 130 }}><Select label="상단 고정" value={draft.pinned ? 'Y' : 'N'} onChange={value => setDraft(previous => ({ ...previous, pinned: value === 'Y' }))}
          options={[{ value: 'N', label: '고정 안 함' }, { value: 'Y', label: '고정' }]} /></div>}
        {admin && <div style={{ width: 110 }}><Select label="게시" value={draft.published ? 'Y' : 'N'} onChange={value => setDraft(previous => ({ ...previous, published: value === 'Y' }))}
          options={[{ value: 'Y', label: '게시' }, { value: 'N', label: '숨김' }]} /></div>}
      </div>
      <TextArea label="내용" rows={16} value={draft.body} onChange={value => setDraft(previous => ({ ...previous, body: value }))} />
      <div className="board-actions">
        <Button label="취소" onClick={() => { setError(''); setMode(post && draft.id !== null ? 'read' : 'list'); }} />
        <span style={{ flex: 1 }} />
        <Button type="submit" label={draft.id === null ? '등록' : '저장'} variant="primary" icon="floppy-disk" isDisabled={!draft.title.trim()} />
      </div>
    </form>}

    <AlertDialog isOpen={confirm !== null} onOpenChange={open => { if (!open) setConfirm(null); }} title={confirm?.what === 'comment' ? '댓글 삭제' : '글 삭제'}
      description={confirm?.what === 'comment' ? '이 댓글을 삭제할까요?' : '이 글을 삭제할까요? 댓글도 함께 지워집니다.'} cancelLabel="취소" actionLabel="삭제" actionVariant="destructive"
      onAction={() => { const target = confirm; setConfirm(null); if (!post || !target) return; run(async () => {
        if (target.what === 'comment') setPost({ ...post, commentList: await adminApi<Comment[]>(`/api/auth/posts/${post.id}/comments/${target.id}`, 'DELETE') });
        else { await adminApi(`/api/auth/posts/${post.id}`, 'DELETE'); setPost(null); await load(); setMode('list'); }
      }); }} />
  </div>;
}
