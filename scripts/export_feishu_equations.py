"""Export a local equation picker for pasting into Feishu's equation editor."""

import html
import json
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def pandoc(source, *options):
    return subprocess.run(
        ["pandoc", *options], input=source, encoding="utf-8", capture_output=True,
        check=True,
    ).stdout


def main():
    source = ROOT / "docs" / "GeoConstruct.md"
    ast = json.loads(pandoc(source.read_text(encoding="utf-8"), "-f", "markdown", "-t", "json"))
    equations = {}

    def walk(node):
        if isinstance(node, dict):
            if node.get("t") == "Math":
                kind, latex = node["c"]
                key = (kind["t"], latex)
                equations[key] = equations.get(key, 0) + 1
            else:
                for value in node.values():
                    walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(ast["blocks"])
    cards = []
    entries = sorted(equations.items(), key=lambda item: item[0][0] != "DisplayMath")
    for index, ((kind, latex), count) in enumerate(entries, 1):
        formula_ast = dict(ast, blocks=[{"t": "Para", "c": [
            {"t": "Math", "c": [{"t": kind}, latex]}
        ]}])
        preview = pandoc(json.dumps(formula_ast), "-f", "json", "-t", "html5", "--mathml")
        label = "独立公式" if kind == "DisplayMath" else "行内公式"
        cards.append(f'''<section><header><b>{index}. {label}</b>
<span>原文出现 {count} 次</span><button type="button">复制公式内容</button></header>
<div class="preview">{preview}</div>
<textarea readonly aria-label="LaTeX 公式内容">{html.escape(latex)}</textarea></section>''')

    template = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>GeoConstruct · 飞书公式粘贴助手</title>
<style>
body{max-width:1050px;margin:36px auto;padding:0 22px;font:16px/1.7 system-ui,"Microsoft YaHei",sans-serif;color:#202735;background:#f5f7fa}
h1{font-size:28px} .intro,section{background:white;border:1px solid #dce2ec;border-radius:12px;padding:22px;margin:18px 0}
header{display:flex;align-items:center;gap:18px;flex-wrap:wrap}header span{color:#64748b;font-size:13px}
button{margin-left:auto;background:#245bdb;color:white;border:0;border-radius:6px;padding:10px 16px;cursor:pointer}
.preview{padding:20px 0;overflow:auto;font-size:20px}textarea{box-sizing:border-box;width:100%;min-height:65px;padding:10px;border:1px solid #ced7e4;border-radius:6px;font:14px/1.5 Consolas,monospace}
code{background:#edf1f8;padding:2px 5px;border-radius:3px}a{color:#245bdb}#status{min-height:26px;color:#245bdb}
</style><h1>GeoConstruct · 飞书公式粘贴助手</h1>
<div class="intro"><b>请粘贴到飞书的公式编辑框，不是正文。</b>
<ol><li>飞书文档中，将光标放在目标位置；行内插入时先输入一个空格。</li>
<li>输入 <code>/eq</code> 并按 Enter，或从 <code>/</code> 菜单选择“公式”。</li>
<li>在本页点击“复制公式内容”，回到飞书公式编辑框按 Ctrl+V，完成后按 Esc。</li></ol>
<p>复制内容不带 <code>$</code> 分隔符。下方预览仅供核对，不表示已经插入飞书。
整篇 Markdown 粘贴不会保证触发公式转换；若已有 <code>$$…$$</code> 普通文本，可先尝试删除并重新键入末尾的美元符号。</p>
<p>公式逐字提取自论文原稿，未替换数学符号。所有转换在本机完成，本页不使用远程脚本。</p>
<a href="https://www.feishu.cn/hc/zh-CN/articles/894598450617" target="_blank" rel="noreferrer">飞书官方：在文档中使用公式</a>
<div id="status" role="status" aria-live="polite"></div></div>
<!-- CARDS -->
<script>
document.querySelectorAll('button').forEach(button=>button.addEventListener('click',async()=>{
  const field=button.closest('section').querySelector('textarea');
  const status=document.getElementById('status');
  try {
    if (!navigator.clipboard?.writeText) throw new Error('clipboard unavailable');
    await navigator.clipboard.writeText(field.value);
  } catch(error) {
    field.focus();field.select();
    if (!document.execCommand('copy')) {
      status.textContent='浏览器未允许自动复制。公式已选中，请按 Ctrl+C。';
      button.textContent='请按 Ctrl+C';return;
    }
  }
  button.textContent='已复制';
  status.textContent='已复制公式内容。请在飞书公式编辑框内粘贴，再按 Esc。';
  setTimeout(()=>button.textContent='复制公式内容',2000);
}));
</script></html>'''
    target = ROOT / "outputs" / "GeoConstruct_feishu_equations.html"
    target.write_text(template.replace("<!-- CARDS -->", "\n".join(cards)), encoding="utf-8")
    print(json.dumps({"output": str(target), "unique_equations": len(equations),
                      "total_equations": sum(equations.values())}, ensure_ascii=False))


if __name__ == "__main__":
    main()
