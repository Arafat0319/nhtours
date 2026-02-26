# Participants Excel 模板（可选）

此模板需**手动创建一次**。若存在 `participants_template.xlsx`，下载 Excel 时将优先使用模板并自动填入当前行程的数据源 URL，实现 **打开即可刷新**。若不存在模板，则使用标准导出（预填数据、无 Power Query）。

## 步骤

### 1. 新建 Excel，添加 Config 表
- 新建工作簿，将第一个 sheet 重命名为 **Config**
- 在 A1 输入占位符：`NHTOURS_URL_PLACEHOLDER`
- 将 A1 命名为：选中 A1 → 左上角名称框输入 `DataSourceURL` 回车

### 2. 添加 Power Query（自网站）
- **数据** → **获取数据** → **自其他源** → **空查询**
- 在 Power Query 编辑器中，**视图** → **高级编辑器**，粘贴以下 M 代码：

```powerquery
let
    URL = Excel.CurrentWorkbook(){[Name="DataSourceURL"]}[Content]{0}[Column1],
    Source = Web.Contents(URL, [Headers=[#"Accept"="*/*"]]),
    Html = Web.Page(Source),
    Table0 = Html{0}[Data],
    #"Promoted Headers" = Table.PromoteHeaders(Table0, [PromoteAllScalars=true])
in
    #"Promoted Headers"
```

- **注意**：若 Excel 版本不同，上述解析可能需调整。更简单的方式：
  - **数据** → **获取数据** → **自网站**
  - 粘贴一个示例 URL（如 `https://yoursite.com/admin/trips/bookings/export/csv?token=test&format=html`）
  - 选择 **表 1**，**转换数据**
  - 在高级编辑器中，将 `Web.Contents("原URL")` 替换为：
    ```powerquery
    URL = Excel.CurrentWorkbook(){[Name="DataSourceURL"]}[Content]{0}[Column1],
    Source = Web.Contents(URL),
    ```
  - 删除或调整后续步骤使最终输出为表 1 的数据

### 3. 加载到 Participants 表
- 在 Power Query 中 **关闭并加载** → 选择 **表** → 加载到 **新建工作表**，命名为 Participants
- 确保 Config 的 A1 为 `NHTOURS_URL_PLACEHOLDER` 且已命名 DataSourceURL

### 4. 另存为模板
- 删除 Contact、Bookings Summary 等多余 sheet（可选，或保留结构）
- 保存为 `participants_template.xlsx` 到本目录
- 确保文件名 exactly 为 `participants_template.xlsx`

### 5. 完成
项目会在下载时读取此模板，将 `NHTOURS_URL_PLACEHOLDER` 替换为实际数据源 URL，导出给用户。
