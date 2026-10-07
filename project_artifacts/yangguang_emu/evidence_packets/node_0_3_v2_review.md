# Evidence Packet Review: yangguang_emu_node_0_3 v2

Status: AWAITING USER APPROVAL

Purpose: First controlled real-customer evidence input for Node [0]-[3] scope, context, asset, and STRIDE evaluation.
Packet SHA-256: `b61daa1b0229924e117b88846db6af73c5395a8dca47cb8a121b55d80a377f82`
Manifest SHA-256: `3dcf5b466628209d69b62ee49402b9d05a6918db76e8288042818407e06857a2`
Config SHA-256: `7189e425f0fad61ddcac685105c87c07aba1825821c4bb3e755a07d39e71335a`
Parser: `pymupdf-page-section-parser` v`1.5.0`

## Size

- Documents: 3
- Sections: 120
- Physical pages: 90
- Blocks: 1041 (28 tables)
- Extracted characters: 37490
- Review-flagged blocks: 0
- Full trace packet: 975610 bytes
- Compact R5 input projection: 133384 bytes; SHA-256 `c95d8c351d5e3f1be0fee1a3ab08eb136544f22e938145748d926037a200aa35`

## Included sources

- `DOC-5067B181346D` — EMU300A-UCN-Ver11-202603.pdf; 9 sections, 12 pages (PDF 15–55), 92 blocks.
- `DOC-DF116E7199E2` — EMU300A网络安全操作手册-UCN-Ver11-202607.pdf; 45 sections, 38 pages (PDF 5–42), 373 blocks.
- `DOC-D9C0DEB31D45` — logger5000用户手册=GUID-00B9E4B6-10C1-4C13-B46E-1BF52C86BC71=1=PDF (产品信息设计部_基础版)=zh-CN (9).pdf; 66 sections, 40 pages (PDF 13–112), 576 blocks.

## Selection rationale

- `SEL-SECURITY-MAIN` — The compact cybersecurity manual is the primary source for scope, deployment, ports, users, security functions, lifecycle controls, and incident handling. Sections: 1 关于本手册; 2 基本安全说明; 3 工业网络安全; 3.1 工业网络安全简介; 3.2 工业网络安全保护目标; 3.3 工业网络安全参考的标准; 4 纵深防御战略; 4.4 用户的缓解措施; 4.3 纵深防御战略的威胁; 5 产品功能及部署情况介绍; 6 端口矩阵; 7 用户列表; 8 用户管理; 8.1 密码管理; 8.2 设置账户保护和会话安全参数; 8.3 LDAP管理; 9 安全退役; 10 安全配置指南; 10.1 部署安全; 10.2 安全启动; 10.3 协议配置; 10.4.2 证书安全维护; 10.4 证书管理和维护; 10.4.1 预置证书风险声明; 10.7 系统还原; 10.5 安全存储; 10.6 恢复出厂设置; 10.9 安全回溯; 10.8 安全对时; 10.9.2 Syslog日志; 10.9.1 操作日志; 10.10 安全更新; 11 报告产品（组件）安全事件说明. PDF pages: 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30.
- `SEL-SECURITY-SWITCH` — The integrated MOXA switch hardening appendix identifies component attack surfaces and available mitigations. Sections: 12 附录：MOXA EDS-408A 安全加固操作指导; 12.1 密码加固; 12.2 交换机密码更新周期管理说明; 12.2.2 Menu密码更新指南; 12.2.1 CLI密码更新指南; 12.3 关闭对工业通讯协议访问的支持; 12.4 关闭交换机 DIP 拨码功能; 12.6 VLAN 配置; 12.5 关闭非必要管理接口; 12.7 固件升级流程; 12.8 配置导入流程; 12.9 安全功能验证. PDF pages: 31, 32, 33, 34, 35, 36, 37, 38, 39, 40, 41, 42.
- `SEL-EMU-TOPOLOGY` — The general EMU manual supplements the security manual with system topology, internal modules, physical communication interfaces, and technical parameters. Sections: 2.1 组网应用; 2.2 主要特点; 4.3 内部结构; 4.6.2 RS485通讯端子连接; 4.6.3 光纤接入（可选）; 4.6.5.1 应用场景; 4.6.5.2 PLC接线; 4.6.6 DI/DO端口接线; 7 附录A：技术参数. PDF pages: 15, 16, 27, 28, 33, 34, 36, 37, 38, 41, 54, 55.
- `SEL-LOGGER-CORE` — Logger5000 is the EMU300A standard internal collector; retain its functions, interfaces, mutable device inventory, logs, recovery, remote access, keys, time, certificates, and update evidence. Sections: 2.1 功能描述; 2.2 组网应用; 2.3 产品介绍; 5.2 外部接口说明; 7 Web界面; 7.3.2 运行环境要求; 7.3.3 操作流程; 7.6.1 设备列表; 7.6.1.4 添加设备; 7.6.1.3 导入; 7.6.1.5 编辑设备; 7.6.1.6 删除设备; 7.6.2 设备日志; 7.9.1 操作日志; 7.9.2 故障记录; 7.9.4 Syslog日志; 7.10.2.4 备份与恢复; 7.10.2.6 公钥导入; 7.10.3 远程维护; 7.10.4 报文导出; 7.10.5 系统时间; 7.10.9 证书安全维护; 13.4 软件安全更新说明. PDF pages: 13, 14, 15, 16, 17, 27, 41, 43, 44, 49, 50, 51, 52, 69, 70, 71, 73, 74, 75, 76, 85, 112.
- `SEL-LOGGER-FORWARDING` — Northbound IEC104, Modbus, cloud, GOOSE, and MMS forwarding paths are major trust boundaries and threat entry points. Sections: 7.10.6.2 转发IEC104服务配置; 7.10.6 转发配置; 7.10.6.2.5 设置IEC104调度模式; 7.10.6.2.1 白名单设置; 7.10.6.2.2 直接生成点表; 7.10.6.2.4 导出IEC104转发点表; 7.10.6.3.3 Modbus TCP快调模式; 7.10.6.3 转发MODBUS服务配置; 7.10.6.3.1 Server模式; 7.10.6.3.2 RTU模式; 7.10.6.3.4 Modbus TCP普通调度模式; 7.10.6.5 转发GOOSE服务配置; 7.10.6.4 转发三方云服务配置. PDF pages: 77, 78, 79, 80, 81.
- `SEL-LOGGER-PORTS` — Runtime port configuration completes the communication-matrix and exposed-interface context. Sections: 7.10.7.1 RS485; 7.10.7.3 AI; 7.10.7.2 以太网; 7.10.7.6 电压电流采样; 7.10.7.4 DI; 7.10.7.5 DO. PDF pages: 82, 83, 84.
- `SEL-LOGGER-UPGRADE` — Firmware and subordinate-device upgrade operations expose integrity-sensitive assets and attack paths. Sections: 8 固件升级; 8.1 升级阳光电源逆变器或PLC从节点; 8.3 升级PLC主节点; 8.2 升级数据采集器. PDF pages: 91, 92.
- `SEL-LOGGER-USERS` — Accounts, roles, passwords, LDAP, session protection, maintenance mode, recovery, and cloud settings define identity and authorization assets. Sections: 9 用户管理; 9.1 初始用户名和密码; 9.2 LDAP管理; 9.4.2 重置管理员账号密码; 9.3 密码管理; 9.4 忘记密码; 9.4.1 重置用户账号密码; 9.6 创建用户账号; 9.5 配置系统提示; 9.9 设置账户保护和会话安全参数; 9.7 删除用户账号; 9.8 重置账号密码; 9.11 LDAP管理; 9.10 启用运维模式; 9.12.2 恢复出厂设置; 9.12 系统维护; 9.12.1 备份与恢复; 9.13.2 三方云; 9.13 通信设置; 9.13.1 阳光云. PDF pages: 93, 94, 95, 96, 97, 98, 99, 100.

## Known gaps

- `GAP-LOGGER4000-SCOPE` (node_0, node_1, node_2, node_3) — A Logger4000 manual is present, but the EMU300A product and cybersecurity manuals identify Logger5000 as the standard internal collector; Logger4000 is excluded until the delivered configuration is confirmed. Disposition: Treat Logger4000 applicability as a customer/configuration question; do not infer its assets or threats in the baseline run.
- `GAP-DIAGRAM-SEMANTICS` (node_1, node_2, node_3) — Native text and figure captions are retained, but topology diagrams have not been manually transcribed into graph relationships. Disposition: Review missing topology only if the first evaluation shows unsupported or absent communication paths.
- `GAP-MIXED-PAGE-BLOCK` (node_1, node_2, node_3) — Logger5000 PDF page 82 merges the end of GOOSE, MMS forwarding, and the start of port parameters into one native PDF text block; its file/page/block anchor is exact but its single assigned section path is broader than the mixed content. Disposition: Require quote plus physical-page/block citation for this block; do not treat its section path alone as proof. Revisit parser splitting only if this locator affects evaluation.
- `GAP-CONTRACT-VARIANTS` (node_0, node_1, node_2, node_3) — The manuals describe optional and contract-dependent functions; the exact customer-enabled feature set is not independently confirmed. Disposition: Preserve uncertainty and produce customer questions instead of asserting optional functions as deployed facts.
- `GAP-LEGAL-BASIS` (node_0, node_2) — Product manuals establish product facts but are not authoritative CRA or prEN 40000 legal sources. Disposition: Use the controlled legal/rule layer for legal conclusions; never fabricate legal support from this packet.

## Approval gate

Approval freezes this packet for the first controlled Node [0]–[3] run. The expert workbook is not included and R4 has not started.
