# CRA Secure Design / TARA 工作流（对齐横向标准 prEN 40000）

已对照目录里四份横向草案改完工作流。这套是 CEN/CLC/JTC 13 按标准化请求 **M/606** 写的 CRA 横向系列（目前均为 **enquiry/draft**，尚未进 OJ，**没有符合性推定**）：

| 文件 | 角色 |
|---|---|
| **prEN 40000-1-1** | 词汇：asset、acceptable risk、residual risk、security objective、likelihood |
| **prEN 40000-1-2** | 原则 + **风险管理要素 §6** + 生命周期活动 §7（TARA 的主骨架） |
| **prEN 40000-1-3** | 漏洞处理（Part II；进技术文件与维护，不是起步威胁分析） |
| **prEN 40000-1-4**（JT013091） | 通用技术控制目录：Threat → Security Objective → Control，映射 Annex I Part I |

`40000-1-2` 的 §6 顺序是：**产品上下文 → 先定义接受准则与方法 → 评估 → 处置 → 沟通 → 评审**。步骤把「判定」放在评分之后，这没问题；但 **接受准则和方法必须在 STRIDE/DREAD 之前写死**，否则 §6.3 不成立。流程中原有两个 `[7]`，后一个按顺序记为 `[8]`。

---

## 修订后的工作流

```text
[0] 法律/产品定界
        CRA Art. 2/3/6–8, Annex III/IV
        ↓
[1] Item / 产品定义  = Product context
        CRA Art. 13(3)
        ISO 21434 Item Definition
        IEC 62443-3-2 ZCR1
        prEN 40000-1-2 §6.2
        同时冻结 §6.3 方法 + 接受准则（STRIDE / DREAD 在此立项）
        ↓
[2] 资产识别  = Asset + cybersecurity objective
        CRA Art. 13(3) “assets to be protected”
        prEN 40000-1-1 §3.4 / §3.15
        prEN 40000-1-2 §6.4.2
        ↓
[3] 威胁场景识别 (STRIDE)
        Commission FAQ 4.1.2
        prEN 40000-1-2 §6.4.3（明确点名 STRIDE）
        prEN 40000-1-4 Threat.* 作为对照目录
        ↓
[4] 影响 + 可行性 (DREAD)
        prEN 40000-1-2 §6.4.4（likelihood × magnitude）
        DREAD 作为选定的定量方法
        ↓
[5] 风险判定 / 接受准则
        CRA Annex I Part I (1)
        prEN 40000-1-2 §6.4.5 + §6.5.1.6
        项目规则：只要风险存在，默认不接受
        ↓
[6] 风险处置 → Secure Design
        CRA Art. 13(2)
        prEN 40000-1-2 §6.5 / §7.3 / §7.4
        prEN 40000-1-4 控制目录 = 最佳实践输出
        prEN 40000标准参考同文件夹横向标准
        各类产品参考垂类标准，17个垂类标准：
        https://docbox.etsi.org/CYBER/EUSR/Open
        芯片类产品参考IEC 50765 和 IEC 50766
        IEC 50765 用于普通芯片，50766 用于有防物理攻击的芯片
        映射客户材料中已有功能；消减不足则额外标注
        ↓
[7] 残余风险 + 技术文件
        prEN 40000-1-2 §6.5.4 / §6.6
        CRA Annex VII(3)(5)(6)、Annex II
        ↓
[8] Annex I 适用性矩阵
        CRA Art. 13(3)、FAQ 4.1.3
        prEN 40000-1-2 Annex C
        prEN 40000-1-4 Annex A/B
```

---

## [0] 法律/产品定界

**约束：** CRA Art. 2、3、6–8，Annex III/IV。横向标准不替代这一步。

**要冻结：** 是否 PDE、是否含 RDPS、Default / Important / Critical、与 RED/MD/其他欧盟法的叠加。`40000-1-2` 把产品及其 RDPS **当作单一系统**（§6.2.3）。

**产出：** Scope statement。

---

## [1] Item / 产品定义（Product context）

这是横向标准里威胁分析真正的第一步。`40000-1-2 §6.2.1.1`：上下文是评估与处置的起点，开发中会迭代。

### 法定 + 标准输入（§6.2.2 写死）

| 输入 | 来源 |
|---|---|
| 功能用例 / user stories | 客户材料 |
| 用户类型 | 客户材料 |
| 市场细分 / 同类产品（state of the art） | 客户 + 公开资料 |
| **已有产品架构** | 客户材料 |
| **已有功能** | 客户材料 |

### 必须记录的五块（§6.2.3）

1. **IPRFU**：intended purpose + reasonably foreseeable use（含用户健康安全、可访问性；Blue Guide 2.8）
2. **产品功能**：含 RDPS 接口与依赖、配置能力、安全功能本身
3. **运行环境**：网络、被集成系统、物理环境、第三方平台约束
4. **架构概览**：关键组件、接口、依赖；RDPS 由谁开发、谁运营
5. **用户描述**：经验/知识/能力；是否弱势群体；是否作为组件被集成

适用时还要记 RDPS 依赖图（运营方、交换数据、信任/认证、降级模式）。

### 在这一步同时完成 §6.3（不要拖到第 5 步才写方法）

`40000-1-2` 要求 **评估之前** 定义并文档化：

- **风险评估与处置方法**（选择：STRIDE 识别 + DREAD 估计）
- **风险接受准则**

方法必须：全生命周期一致、针对本产品有 justification、对齐 state of the art、同时覆盖 **单项风险和聚合风险**。

接受准则至少考虑：监管因素、合同/供应链分担、风险性质、用户性质、产品性质、SOTA 与社会当前价值。

项目规则写进 §6.3 输出：

> **If a risk exists, it is not accepted by default.**
>
> 处置优先级按 §6.5.1.6：**Avoid → Mitigate → Accept → Transfer**。Accept 只能在规避/消减之后、对照准则书面 justification；禁止静默接受。

**产出：** Product context + 方法说明（STRIDE/DREAD 量表与阈值）+ 接受准则。

**对应评估准则：** §6.2.5 / §6.3.5（技术文件里要有 due diligence 证据）。

---

## [2] 资产识别（§6.4.2）

`40000-1-1 §3.4`：asset = anything that has value to an individual, an organization or a government。

`§3.15`：security objective = result to be achieved concerning the protection from cyber threats。

横向标准要求 **资产和网络安全目标一起识别**，不是只列资产。

**资产类型（§6.4.2.1 最低覆盖）：**

- 存储/处理/传输的数据（密钥、令牌、个人数据、财务数据、日志）
- 产品执行的功能（配置、通信、密码协议完整性）
- 软硬件组件及其接口
- 与使用相关的用户侧资产
- 财产、他人、家畜、环境、公共利益
- 网络与相邻设备

**输入：** [1] 的 product context。

**产出：** 资产清单 + 每项对应的 cybersecurity objectives。

**判定：** 清单存在且 complete（§6.4.2.5）。

>针对安全功能做主要审核，确认是否有漏掉的安全功能。每个产品的安全功能全集参考对应的垂类的标准，如果没有垂类标准参考横向标准。
垂类标准中有的安全功能，但是没有被识别出来的功能，单独列出来。

---

## [3] 威胁场景识别（STRIDE）

`40000-1-2 §6.4.3` 把威胁建模定义为结构化识别，并 **点名 STRIDE**（同时列出 TVRA、attack trees、PASTA）。可选对照：威胁目录 TR JT013097、MITRE、垂直标准、**40000-1-4 的 Threat.\***。

**每个威胁必须写清（§6.4.3.3）：**

- 针对的 asset(s)
- 被破坏的 cybersecurity objective(s)
- 破坏原因（cause of compromise）

**输入：** 资产与目标、product context、常见威胁、相关 known exploitable vulnerabilities。

**产出：** 按资产列出的威胁清单。

**判定：** 每项资产都有威胁列表，且 sufficient。

STRIDE 与 `40000-1-4` 目录的对照（识别时用，不是替代 [8]）：

| STRIDE | 1-4 典型 Threat / SO |
|---|---|
| Spoofing | Threat.UnauthorizedAccess → SO.AccessControl / ComAuth |
| Tampering | Data*Tampering、SoftwareUpdateTampering → Integrity SOs |
| Repudiation | NotReportedUnauthorizedAccess、TamperingUndetected → Report/Log SOs |
| Information Disclosure | Data*Disclosure、UnnecessaryDataMisuse → Confidentiality / DataMinimization |
| Denial of Service | AvailabilityDegradation*、ExtServiceAvailabilityDegradation |
| Elevation of Privilege | UnnecessaryFunctionalityExploitation、UnsecureDefaultConfigExploitation |

(a)(b)(c) 对应 KnownVulnerability / UnsecureDefault / Unpatchable 等，在 STRIDE 之外单独勾，避免漏掉投放条件。
>针对安全功能做主要审核，确认是否有漏掉的安全功能。每个产品的安全功能全集参考对应的垂类的标准，如果没有垂类标准参考横向标准。
垂类标准中有的安全功能，但是没有被识别出来的功能，单独列出来。

---

## [4] 影响 + 可行性（DREAD = §6.4.4 的估计方法）

横向标准 **不规定量表**，只规定风险必须由：

- **likelihood of occurrence**（易被利用/发生的难易，`40000-1-1 §3.9`）
- **magnitude of potential loss or disruption**

估计出来，且与 §6.3 选定的方法一致。可用定性矩阵或定量打分（§6.4.4 NOTE 1–2）。DREAD 落在「定量打分」这一类。

建议把五维拆进两个法定因子，避免和标准语言对不上：

| 法定因子 | DREAD 维 |
|---|---|
| Magnitude | Damage，Affected users |
| Likelihood | Reproducibility，Exploitability，Discoverability |

**硬性规则：** Damage 必须显式覆盖用户健康与安全、以及对相邻设备/网络的影响（对应 Annex I (i) 和 §6.3 的 health and safety / attack scalability）。

**产出（§6.4.4.4）：** 每个威胁的 likelihood、magnitude、综合 risk。

---

## [5] 风险判定（§6.4.5）—— 使用[1]输出的接受准则

§6.4.5 的任务是：对照 [1] 已冻结的接受准则，标出 **不可接受、必须处置** 的风险，并为拟接受的残余风险写 justification。

叠项目规则和 §6.5.1.6：

| 情况 | 动作 |
|---|---|
| DREAD 显示风险存在 | **默认进入处置**，不得直接 Accept |
| 可改产品上下文去掉功能/组件 | Avoid（优先） |
| 可加控制降低 L 或 I | Mitigate |
| 固有功能、消减/规避会破坏 IPRFU | 才允许考虑 Accept，且必须披露 + 给用户缓解措施（§6.5.1.4 / §6.5.3） |
| 残余交给用户环境 | Transfer，且必须沟通（§6.5.1.5）；不能代替产品内建控制 |

**产出：** 已评价风险清单 +（仅当真正接受时）残余接受 justification。

---

## [6] 风险处置 → Secure Design

这一步对应横向标准的三条链，不能只写「加个控制」：

1. **§6.5 处置决定**（Avoid / Mitigate / Accept / Transfer，低优先级不得在高优先级仍可用时选用；Mitigate 后 **必须重评**）
2. **§7.3 产品网络安全要求**：把处置变成可追溯、可验证的要求；从控制目录选 control
3. **§7.4 安全架构与设计**：信任边界、接口认证与输入校验、攻击面最小化；落实 §5.3 security by design、§5.4 secure by default；第三方/RDPS 做 due diligence（§7.11）

**最佳实践来源（按标准自己的排序）：**

- **prEN 40000-1-4**（JT013091）——与 CRA 基本要求直接相关的控制目录（§7.3 NOTE 2 第一项）
- 必要时补充：ETSI EN 303 645、EN IEC 62443-4-2、ISO/IEC 15408-2、ISO/IEC 27002、BSI「State of the art」指南

对每条不可接受风险输出一行 **Secure Design 映射**（最佳实践 + 客户已有功能 + 缺口标注）：

| 字段 | 填什么 |
|---|---|
| Risk ID | 来自 [3][4][5] |
| 1-4 Threat / SO | 目录中的最佳实践目标 |
| 推荐控制 | 1-4 机制 ID，如 `[AUM-2]` `[GEC-9]` `[SUM-2]` `[ACM-2]` `[CRY-1]` |
| 客户材料中已有功能 | 映射 [1] 的 existing functions / architecture（实现、配置、流程均可） |
| Coverage | Covered / Partial / Missing |
| **Gap 标注** | 已有功能 + 推荐控制仍不足以把风险打到准则以下 → **额外标注**，并列出需新增的控制（1-4 说：残余风险可以、也往往需要目录外的进一步控制） |
| 生命周期落点 | planning / design / development / production / delivery / maintenance（Art. 13(2)） |

**§7.4 设计最低要检查：** 信任边界（含 RDPS）、最小权限、攻击面、defence in depth、不靠保密实现安全、默认安全配置。

**产出：** 每条风险的处置决定 + 产品网络安全要求 + 安全架构/设计说明 + Gap 清单。

---

## [7] 残余风险 + 技术文件

Mitigate 后重评得到 **residual cybersecurity risk**（`40000-1-1 §3.14`）。

**沟通（§6.6，对应 Annex II）：** 向受影响利益相关方说明残余风险、建议缓解、上下文假设、对用户/下游集成商的期望。相关内容进 CRA Annex II（尤其第 4、5、8 点）。

**技术文件最低（Annex VII）：**

- (3) 针对其进行设计/开发/生产/交付/维护的网络安全风险评估，含 Part I 如何适用
- (5) 用了哪些标准（本阶段写 prEN 40000-1-x 草案 + 其他）或替代方案
- (6) 验证测试报告


**产出：** 残余风险登记、Annex II 用户告知草稿、Annex VII 风险评估章节。使用[1]输出的风险接受准则判定风险是否可接受。

---

## [8] Annex I 适用性矩阵（法定闭合）

放在处置和残余之后：这时已经知道 **适用哪些条款、用什么控制、还差什么**。

对 Part I (2)(a)–(m) 逐条：Applicable? / 若否则 justification / 相关威胁 / 1-4 控制 / 客户已有功能 / Gap / 证据。

Part I (1) 和 **整个 Part II** 必须说明如何落实。

横向标准的现成映射：

- `40000-1-2` Annex C：过程条款 ↔ Annex I Part I (1) 和 (2) 的「基于风险」
- `40000-1-4` Annex A/B：Threat / SO / Control ↔ Annex I Part I 各分项
  （1-2 自己写明：Part I (2) 的产品控制在 JT013091，不在 1-2）

---

## 起步时到底要客户给什么（抽象层最低集）

对应 `40000-1-2 §6.2.2`，威胁分析开始前向客户要：

1. 功能用例 / 用户故事
2. 用户类型（含是否专业用户、儿童等弱势群体、是否被当作组件集成）
3. 市场定位与同类产品
4. **现有架构**（含云/RDPS、接口、信任边界草图即可）
5. **现有安全与非安全功能清单**（这是第 [6] 步映射的原材料）
6. IPRFU 声明（说明书、宣传材料、技术文件里怎么写）
7. 预期使用年限 / 拟声明的 support period
8. 已知第三方组件与供应链角色

没有 4 和 5，STRIDE 可以开，但第 [6] 步的「映射客户已有功能 / Gap 标注」做不成。

---

## 每步约束一览

| 步 | 法规 | 横向标准 | 方法 | 默认策略 |
|---|---|---|---|---|
| 0 | CRA Art. 2/3/6–8 | 范围含 RDPS | — | — |
| 1 | Art. 13(3) | **1-2 §6.2 + §6.3**；21434 Item Def；62443-3-2 ZCR1 | 上下文建立 | 方法/准则先冻结 |
| 2 | Art. 13(3) assets | **1-2 §6.4.2**；1-1 asset/SO | — | 资产与目标成对 |
| 3 | FAQ 4.1.2 | **1-2 §6.4.3**；1-4 Threat 目录 | **STRIDE** | 每资产都要有威胁 |
| 4 | — | **1-2 §6.4.4** | **DREAD** | L × I，覆盖 safety |
| 5 | Annex I Part I (1) | **1-2 §6.4.5 / §6.5.1.6** | 对照 [1] 的准则 | **有风险默认不接受** |
| 6 | Art. 13(2) | **1-2 §6.5, §7.3, §7.4**；**1-4 控制目录** | 控制选型 + 架构 | 映射已有功能；不足则 Gap |
| 7 | Annex VII, II | **1-2 §6.6**；**1-3** | — | 残余必须沟通 |
| 8 | Art. 13(3), FAQ 4.1.3 | 1-2 Annex C；1-4 Annex A/B | — | Part II 不可 N/A |

---
