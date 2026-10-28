import { Children, isValidElement, useEffect, type ReactNode } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import { useLocation } from "react-router-dom";
import remarkGfm from "remark-gfm";
// Jedan izvor: isti dokument je u docs/ (GitHub) i u aplikaciji (spec. §20.1).
import manual from "../../../docs/korisnicko-uputstvo.md?raw";

const images = import.meta.glob("../../../docs/uputstvo-slike/*.jpg", { eager: true, query: "?url", import: "default" }) as Record<string, string>;
const imageUrl = (src: string) => images[`../../../docs/${src}`] ?? src;

/** Isti „slug” kao GitHub, da linkovi iz sadržaja rade i u aplikaciji i na GitHub-u. */
function slug(children: ReactNode): string {
  const text = Children.toArray(children)
    .map((c) => (typeof c === "string" ? c : isValidElement(c) ? slug((c.props as { children?: ReactNode }).children) : ""))
    .join("");
  return text.toLowerCase().trim().replace(/[^\p{L}\p{N}\s-]/gu, "").replace(/\s/g, "-");
}

const components: Components = {
  h1: ({ children }) => <h1 id={slug(children)}>{children}</h1>,
  h2: ({ children }) => <h2 id={slug(children)}>{children}</h2>,
  h3: ({ children }) => <h3 id={slug(children)}>{children}</h3>,
  a: ({ href, children }) =>
    href?.startsWith("#") ? <a href={href}>{children}</a> : <a href={href} target="_blank" rel="noreferrer">{children}</a>,
  img: ({ src, alt }) => <img src={imageUrl(String(src ?? ""))} alt={alt ?? ""} loading="lazy" />,
  table: ({ children }) => (
    <div className="overflow-x-auto">
      <table>{children}</table>
    </div>
  ),
};

export default function HelpPage() {
  const { hash } = useLocation();
  useEffect(() => {
    if (hash) document.getElementById(decodeURIComponent(hash.slice(1)))?.scrollIntoView();
  }, [hash]);
  return (
    <article className="help-doc mx-auto max-w-4xl rounded-xl border border-slate-200 bg-white p-6 shadow-sm dark:border-slate-800 dark:bg-slate-900">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {manual}
      </ReactMarkdown>
    </article>
  );
}
