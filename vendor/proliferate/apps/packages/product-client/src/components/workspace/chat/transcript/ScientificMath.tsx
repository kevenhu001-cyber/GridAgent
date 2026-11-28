import { useMemo } from "react";
import katex from "katex";
import "katex/dist/katex.min.css";

export function ScientificMath({source, display}: {source: string; display: boolean}) {
  const html = useMemo(() => {
    if (source.length > 4096) return null;
    try {
      return katex.renderToString(source, {
        displayMode: display,
        output: "htmlAndMathml",
        throwOnError: true,
        trust: false,
        strict: "error",
        maxExpand: 200,
        maxSize: 20,
      });
    } catch {
      return null;
    }
  }, [source, display]);
  const className = display ? "block max-w-full overflow-x-auto py-1" : "inline";
  // Only KaTeX-generated markup; never raw model or imported HTML.
  return html === null ?
    <span className={className} data-scientific-math="invalid">{source}</span> :
    <span className={className} data-scientific-math={display ? "display" : "inline"}
      dangerouslySetInnerHTML={{__html: html}} />;
}
