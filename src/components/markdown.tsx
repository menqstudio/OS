// A small, dependency-free Markdown renderer for agent replies.
//
// SAFETY: every piece of source text is HTML-escaped BEFORE any markup is added,
// and only a fixed set of known-safe tags is ever emitted. Link hrefs are
// restricted to http(s). There is no path for model output to inject raw HTML,
// so the escaped result is safe to hand to dangerouslySetInnerHTML.

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

// Inline formatting. Input MUST already be HTML-escaped.
function inline(s: string): string {
  let out = s;
  // links [text](http…) — href limited to http/https, text kept as-is (escaped)
  out = out.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,
    (_m, text, url) => `<a href="${url}" target="_blank" rel="noopener noreferrer">${text}</a>`);
  // inline code
  out = out.replace(/`([^`]+)`/g, '<code>$1</code>');
  // bold then italic (bold first so ** isn't eaten by italic)
  out = out.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  out = out.replace(/(^|[^*])\*([^*\n]+)\*/g, '$1<em>$2</em>');
  // underscore italics only at word boundaries, so identifiers like
  // some_var_name and __init__ are left untouched.
  out = out.replace(/(^|\W)_([^_\n]+)_(?=\W|$)/g, '$1<em>$2</em>');
  return out;
}

/** Render a Markdown subset to a safe HTML string. */
export function renderMarkdown(src: string): string {
  const lines = src.replace(/\r\n/g, '\n').split('\n');
  const out: string[] = [];
  let listType: 'ul' | 'ol' | null = null;
  const closeList = () => {
    if (listType) {
      out.push(`</${listType}>`);
      listType = null;
    }
  };

  let i = 0;
  while (i < lines.length) {
    const line = lines[i];

    // fenced code block ```
    if (/^```/.test(line.trim())) {
      closeList();
      const buf: string[] = [];
      i += 1;
      while (i < lines.length && !/^```\s*$/.test(lines[i].trim())) {
        buf.push(lines[i]);
        i += 1;
      }
      i += 1; // skip closing fence (if present)
      out.push(`<pre><code>${escapeHtml(buf.join('\n'))}</code></pre>`);
      continue;
    }

    // heading
    const h = line.match(/^(#{1,6})\s+(.*)$/);
    if (h) {
      closeList();
      const level = Math.min(h[1].length + 2, 6); // # -> h3 … keep sizes modest
      out.push(`<h${level}>${inline(escapeHtml(h[2]))}</h${level}>`);
      i += 1;
      continue;
    }

    // unordered list
    const ul = line.match(/^\s*[-*]\s+(.*)$/);
    if (ul) {
      if (listType !== 'ul') {
        closeList();
        out.push('<ul>');
        listType = 'ul';
      }
      out.push(`<li>${inline(escapeHtml(ul[1]))}</li>`);
      i += 1;
      continue;
    }

    // ordered list
    const ol = line.match(/^\s*\d+\.\s+(.*)$/);
    if (ol) {
      if (listType !== 'ol') {
        closeList();
        out.push('<ol>');
        listType = 'ol';
      }
      out.push(`<li>${inline(escapeHtml(ol[1]))}</li>`);
      i += 1;
      continue;
    }

    // blank line ends any block
    if (line.trim() === '') {
      closeList();
      i += 1;
      continue;
    }

    // paragraph: gather consecutive plain lines
    closeList();
    const para: string[] = [line];
    i += 1;
    while (
      i < lines.length &&
      lines[i].trim() !== '' &&
      !/^```/.test(lines[i].trim()) &&
      !/^(#{1,6})\s/.test(lines[i]) &&
      !/^\s*[-*]\s/.test(lines[i]) &&
      !/^\s*\d+\.\s/.test(lines[i])
    ) {
      para.push(lines[i]);
      i += 1;
    }
    out.push(`<p>${inline(escapeHtml(para.join('\n'))).replace(/\n/g, '<br />')}</p>`);
  }
  closeList();
  return out.join('\n');
}

/** Render agent/assistant Markdown text as safe HTML. */
export function Markdown({ text }: { text: string }) {
  return <div className="md" dangerouslySetInnerHTML={{ __html: renderMarkdown(text) }} />;
}
