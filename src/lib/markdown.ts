import { marked } from "marked";
import DOMPurify from "dompurify";

// Documents are markdown. Render to sanitized HTML for the viewer — AI-authored
// docs (M4) could contain anything, so we sanitize even though it's all local.
export function renderMarkdown(md: string): string {
  const html = marked.parse(md, { async: false }) as string;
  return DOMPurify.sanitize(html);
}
