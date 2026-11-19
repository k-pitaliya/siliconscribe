import re
import os
import shutil
import markdown
from xhtml2pdf import pisa
import pypdf

def clean_math_and_syntax(text):
    text = re.sub(r'\\mu\\text\{m\}\^2', '&mu;m<sup>2</sup>', text)
    text = re.sub(r'\\mu m\^2', '&mu;m<sup>2</sup>', text)
    text = re.sub(r'\\mu', '&mu;', text)
    text = re.sub(r'\\le', '&le;', text)
    text = re.sub(r'\\ge', '&ge;', text)
    text = re.sub(r'\\approx', '&asymp;', text)
    text = re.sub(r'\\times', '&times;', text)
    text = re.sub(r'\\rightarrow', '&rarr;', text)
    text = re.sub(r'\\longrightarrow', '&rarr;', text)
    text = re.sub(r'\$([^\$]+)\$', r'<i>\1</i>', text)
    return text

def convert_report():
    with open("docs/EC486_Minor_Project_Report.md", "r", encoding="utf-8") as f:
        md_content = f.read()

    cleaned_md = clean_math_and_syntax(md_content)

    html_body = markdown.markdown(
        cleaned_md,
        extensions=['tables', 'fenced_code']
    )

    custom_html = f'''<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>EC486 Minor Project Progress Report - Kushal Pitaliya (23EC105)</title>
<style>
@page {{
    size: a4 portrait;
    margin-top: 18mm;
    margin-bottom: 18mm;
    margin-left: 16mm;
    margin-right: 16mm;
    @frame header {{
        -pdf-frame-content: page_header;
        top: 6mm;
        left: 16mm;
        right: 16mm;
        height: 10mm;
    }}
    @frame footer {{
        -pdf-frame-content: page_footer;
        bottom: 6mm;
        left: 16mm;
        right: 16mm;
        height: 10mm;
    }}
}}

body {{
    font-family: Helvetica, Arial, sans-serif;
    font-size: 8.8pt;
    line-height: 1.38;
    color: #1e293b;
    text-align: justify;
}}

#page_header {{
    font-size: 7pt;
    color: #64748b;
    border-bottom: 0.5pt solid #cbd5e1;
    padding-bottom: 2pt;
    text-align: right;
}}

#page_footer {{
    font-size: 7pt;
    color: #64748b;
    border-top: 0.5pt solid #cbd5e1;
    padding-top: 2pt;
}}

.footer-table {{
    width: 100%;
    border: none;
}}
.footer-table td {{
    border: none;
    padding: 0;
}}

h1 {{
    font-size: 12pt;
    color: #1e3a8a;
    font-weight: bold;
    margin-top: 8pt;
    margin-bottom: 3pt;
    border-bottom: 0.75pt solid #1e3a8a;
    padding-bottom: 1.5pt;
    page-break-after: avoid;
}}

h2 {{
    font-size: 10pt;
    color: #0f172a;
    font-weight: bold;
    margin-top: 7pt;
    margin-bottom: 2.5pt;
    page-break-after: avoid;
}}

h3 {{
    font-size: 9pt;
    color: #334155;
    font-weight: bold;
    margin-top: 6pt;
    margin-bottom: 2pt;
    page-break-after: avoid;
}}

p {{
    margin-top: 0;
    margin-bottom: 4pt;
}}

ul, ol {{
    margin-top: 0;
    margin-bottom: 4pt;
    padding-left: 13pt;
}}

li {{
    margin-bottom: 1.5pt;
}}

table {{
    width: 100%;
    border-collapse: collapse;
    margin-top: 5pt;
    margin-bottom: 6pt;
    font-size: 7.8pt;
    page-break-inside: avoid;
}}

th {{
    background-color: #1e3a8a;
    color: #ffffff;
    font-weight: bold;
    text-align: left;
    padding: 3.5pt 4.5pt;
    border: 0.5pt solid #1e3a8a;
}}

td {{
    padding: 3pt 4.5pt;
    border: 0.5pt solid #cbd5e1;
    vertical-align: top;
}}

tr:nth-child(even) td {{
    background-color: #f8fafc;
}}

pre {{
    font-family: Courier, monospace;
    font-size: 6.5pt;
    line-height: 1.18;
    background-color: #f8fafc;
    border: 0.5pt solid #cbd5e1;
    padding: 4pt 5pt;
    border-radius: 2pt;
    margin-top: 3pt;
    margin-bottom: 5pt;
    page-break-inside: avoid;
    white-space: pre-wrap;
}}

code {{
    font-family: Courier, monospace;
    font-size: 7.5pt;
    background-color: #f1f5f9;
    color: #0f172a;
    padding: 1pt 2pt;
    border-radius: 2pt;
}}

blockquote {{
    background-color: #f8fafc;
    border-left: 2pt solid #3b82f6;
    margin: 4pt 0;
    padding: 3pt 6pt;
    font-style: italic;
    color: #334155;
    page-break-inside: avoid;
}}

hr {{
    border: 0;
    border-top: 0.5pt solid #cbd5e1;
    margin: 5pt 0;
}}
</style>
</head>
<body>

<div id="page_header">
    CHARUSAT &bull; CSPIT &bull; EC Department &bull; EC486 Minor Project Progress Report
</div>

<div id="page_footer">
    <table class="footer-table">
        <tr>
            <td style="text-align: left;">Kushal Pitaliya (23EC105) &mdash; SiliconScribe Progress Report</td>
            <td style="text-align: right;">Page <pdf:pagenumber> of <pdf:pagecount></td>
        </tr>
    </table>
</div>

<div class="content">
{html_body}
</div>

</body>
</html>
'''

    out_pdf = "docs/EC486_Minor_Project_Report.pdf"
    with open(out_pdf, "wb") as f:
        pisa_status = pisa.CreatePDF(custom_html, dest=f)

    if pisa_status.err:
        print("Error during PDF generation")
        return

    reader = pypdf.PdfReader(out_pdf)
    num_pages = len(reader.pages)
    file_size = os.path.getsize(out_pdf)
    print(f"Generated {out_pdf}: {num_pages} pages, {file_size} bytes")

    # Copy to root workspace
    root_pdf = "EC486_Minor_Project_Report.pdf"
    shutil.copy(out_pdf, root_pdf)
    print(f"Copied to root: {root_pdf}")

    # Copy to artifact directory
    artifact_dir = "/Users/kushalpitaliya/.gemini/antigravity/brain/dec5c233-339c-4701-af2a-fad175324425"
    if os.path.exists(artifact_dir):
        shutil.copy(out_pdf, os.path.join(artifact_dir, "EC486_Minor_Project_Report.pdf"))
        shutil.copy("docs/EC486_Minor_Project_Report.md", os.path.join(artifact_dir, "EC486_Minor_Project_Report.md"))
        print(f"Copied to artifact dir: {artifact_dir}")

if __name__ == "__main__":
    convert_report()
