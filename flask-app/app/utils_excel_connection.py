# -*- coding: utf-8 -*-
"""
为下载的 Excel 文件注入 Web 数据连接，使打开后可点击刷新获取最新数据。
并提供 Power Query 模板的占位符替换（用于预配置好 Power Query 的模板）。
"""

import zipfile
import io
import xml.etree.ElementTree as ET

# OOXML 命名空间
NS = {
    'main': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main',
    'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships',
}

def _register_namespaces():
    for prefix, uri in NS.items():
        ET.register_namespace(prefix, uri)

def _escape_xml(s):
    """转义 XML 特殊字符"""
    return (s
        .replace('&', '&amp;')
        .replace('<', '&lt;')
        .replace('>', '&gt;')
        .replace('"', '&quot;')
        .replace("'", '&apos;'))


def inject_web_connection(xlsx_bytes, data_url, connection_name='Participants'):
    """
    向 xlsx 字节流注入 Web 连接和 queryTable，使 Participants 表可刷新。
    
    :param xlsx_bytes: 原始 xlsx 文件字节
    :param data_url: 数据源 URL（应返回 HTML 表格）
    :param connection_name: 连接名称
    :return: 修改后的 xlsx 字节
    """
    _register_namespaces()
    data_url_escaped = _escape_xml(data_url)
    
    output = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(xlsx_bytes), 'r') as zin:
        with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as zout:
            conn_id = 1
            conn_rel_id = 'connId1'
            
            # 1. 创建 connections.xml (webPr 需 tables 子元素，引用 HTML 中 id="participants" 的表格)
            connections_xml = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<connections xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <connection id="{conn_id}" name="{connection_name}" type="4" refreshedVersion="1" background="1" saveData="1">
    <webPr url="{data_url_escaped}" sourceData="1" parsePre="1" consecutive="1" xl2000="1" htmlTables="1">
      <tables count="1"><s v="participants"/></tables>
    </webPr>
  </connection>
</connections>'''
            
            # 2. 复制所有文件并修改需要的
            for item in zin.infolist():
                data = zin.read(item.filename)
                
                if item.filename == 'xl/_rels/workbook.xml.rels':
                    # 添加 connections 的 relationship
                    root = ET.fromstring(data)
                    rel_ns = 'http://schemas.openxmlformats.org/package/2006/relationships'
                    ET.register_namespace('', rel_ns)
                    rel = root.find(f'.//{{{rel_ns}}}Relationship[@Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/connections"]')
                    if rel is None:
                        max_id = 0
                        for r in root.findall(f'.//{{{rel_ns}}}Relationship'):
                            rid = r.get('Id', '')
                            if rid.startswith('rId'):
                                try:
                                    max_id = max(max_id, int(rid[3:]))
                                except ValueError:
                                    pass
                        new_id = f'rId{max_id + 1}'
                        child = ET.SubElement(root, f'{{{rel_ns}}}Relationship')
                        child.set('Id', new_id)
                        child.set('Type', 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/connections')
                        child.set('Target', 'connections.xml')
                        data = ET.tostring(root, encoding='unicode').encode('utf-8')
                
                elif item.filename == '[Content_Types].xml':
                    # 添加 connections 的 Override
                    if b'connections.xml' not in data:
                        root = ET.fromstring(data)
                        ct_ns = 'http://schemas.openxmlformats.org/package/2006/content-types'
                        ov = root.find(f'.//{{{ct_ns}}}Override[@PartName="/xl/connections.xml"]')
                        if ov is None:
                            default = root.find(f'{{{ct_ns}}}Default')
                            ov = ET.SubElement(root, f'{{{ct_ns}}}Override')
                            ov.set('PartName', '/xl/connections.xml')
                            ov.set('ContentType', 'application/vnd.openxmlformats-officedocument.spreadsheetml.connections+xml')
                            data = ET.tostring(root, encoding='unicode').encode('utf-8')
                
                elif item.filename == 'xl/worksheets/sheet1.xml':
                    # 向 Participants 表（第一个 sheet）添加 queryTable
                    root = ET.fromstring(data)
                    qt_ns = NS['main']
                    # 检查是否已有 queryTable
                    qt = root.find(f'.//{{{qt_ns}}}queryTable')
                    if qt is None:
                        # 在 sheetData 之后添加 queryTable
                        sheet_data = root.find(f'{{{qt_ns}}}sheetData')
                        if sheet_data is not None:
                            idx = list(root).index(sheet_data) + 1
                            qt = ET.Element(f'{{{qt_ns}}}queryTable')
                            qt.set('name', 'Participants')
                            qt.set('connectionId', str(conn_id))
                            qt.set('ref', 'A1')  # 目标区域左上角，刷新时从 A1 开始填充
                            qt.set('refreshOnLoad', '1')  # 打开时自动刷新
                            qt.set('fillFormulas', '0')
                            qt.set('removeDataOnSave', '1')
                            root.insert(idx, qt)
                            data = ET.tostring(root, encoding='unicode').encode('utf-8')
                
                zout.writestr(item, data)
            
            # 3. 添加 connections.xml
            zout.writestr('xl/connections.xml', connections_xml.encode('utf-8'))
    
    output.seek(0)
    return output.getvalue()


# 模板占位符，与 participants_template_README 中的说明一致
TEMPLATE_URL_PLACEHOLDER = 'NHTOURS_URL_PLACEHOLDER'


def prepare_template_with_url(template_path, data_url):
    """
    加载预配置 Power Query 的 Excel 模板，将占位符替换为实际数据源 URL。
    模板中 Config 表 A1 应包含 NHTOURS_URL_PLACEHOLDER，并命名为 DataSourceURL。
    
    :param template_path: 模板文件路径
    :param data_url: 数据源 URL（HTML 接口）
    :return: 替换后的 xlsx 字节，失败时返回 None
    """
    import os
    if not os.path.isfile(template_path):
        return None
    url_escaped = _escape_xml(data_url)
    placeholder_bytes = TEMPLATE_URL_PLACEHOLDER.encode('utf-8')
    replacement_bytes = url_escaped.encode('utf-8')
    output = io.BytesIO()
    try:
        with zipfile.ZipFile(template_path, 'r') as zin:
            with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as zout:
                for item in zin.infolist():
                    data = zin.read(item.filename)
                    if placeholder_bytes in data:
                        data = data.replace(placeholder_bytes, replacement_bytes)
                    zout.writestr(item, data)
    except Exception:
        return None
    output.seek(0)
    return output.getvalue()
