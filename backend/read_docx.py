"""读取 docx 文件内容并输出为文本"""
import sys
import zipfile
import xml.etree.ElementTree as ET


def read_docx(path: str) -> str:
    """从 docx 文件中提取纯文本内容"""
    ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
    parts = []
    with zipfile.ZipFile(path, 'r') as z:
        with z.open('word/document.xml') as f:
            tree = ET.parse(f)
            root = tree.getroot()
            for para in root.iter('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p'):
                texts = []
                for run in para.iter('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t'):
                    if run.text:
                        texts.append(run.text)
                line = ''.join(texts).strip()
                if line:
                    parts.append(line)
    return '\n'.join(parts)


if __name__ == '__main__':
    path = sys.argv[1] if len(sys.argv) > 1 else r'g:\软件开发\AI药物\AI模式精准药物设计系统-创意文档-v3.0.docx'
    content = read_docx(path)
    print(content)
