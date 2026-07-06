# Third-Party Notices

## RFM-CLV-Amazon-Analytics（仅作功能参考，未包含其代码）

- Repository: https://github.com/Mst-KrgZ/RFM-CLV-Amazon-Analytics
- Author: Mesut Karagöz
- Reference area: `app/streamlit_app.py` 中的 Business Recommendations 页面
- Included source code: None

该仓库的README声称使用MIT许可证，但审查时仓库中没有完整的LICENSE文件或MIT许可
文本。因此，本项目没有复制或修改该仓库的源代码。会员运营建议功能仅参考其“按分层
展开建议卡片、展示动态人数和金额、提供优先级矩阵”的产品结构，数据适配、10类策略、
动态推荐原因、异常处理、下载和Streamlit实现均为兼容重写。该参考仓库不是本项目的
运行时依赖。

## Data-Storytelling-Dashboard

- Repository: https://github.com/AmirhosseinHonardoust/Data-Storytelling-Dashboard
- Author and copyright holder: Amir
- License: MIT License
- Reference files: `app/app.py` and `app/utils/data_utils.py`
- Files adapted in this project: `app/app.py`

This project's `app/app.py` adapts the reference dashboard's high-level
Streamlit presentation pattern: wide page layout, sidebar controls, KPI metric
columns, two-column chart/table sections, download buttons, and a footer source
note. All labels and application logic were rewritten for this project's
exported RFM artifacts. No synthetic dataset, RFM implementation, cohort logic,
or runtime dependency on the reference repository is included. The loader and
validation code in `app/dashboard_data.py` is original to this project.

### MIT License

Copyright (c) 2025 Amir

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
