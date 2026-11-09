import { Marked, type Tokens } from "marked";
import DOMPurify from "dompurify";

function escape(text: string) {
  return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

const marked = new Marked({ gfm: true, breaks: true });
marked.use({
  renderer: {
    code({ text, lang }: Tokens.Code) {
      const language = (lang || "").trim().split(/\s+/)[0];
      return `<div class="md-code"><div class="md-code-head"><span>${escape(language || "code")}</span>` +
        `<button type="button" data-copy-code="1">복사</button></div><pre><code>${escape(text)}</code></pre></div>`;
    },
    link(this: { parser: { parseInline(tokens: Tokens.Link["tokens"]): string } }, { href, tokens }: Tokens.Link) {
      return `<a href="${escape(href)}" target="_blank" rel="noopener noreferrer">${this.parser.parseInline(tokens)}</a>`;
    },
  },
});

/** Render model Markdown to sanitized HTML. Unclosed code fences while streaming render as code. */
export function renderMarkdown(source: string) {
  let text = source;
  if (((text.match(/^```/gm) || []).length % 2) === 1) text += "\n```";
  const html = marked.parse(text, { async: false }) as string;
  return DOMPurify.sanitize(html, { ADD_ATTR: ["target"] });
}
