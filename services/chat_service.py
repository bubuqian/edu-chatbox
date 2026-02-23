"""Gemini 聊天服务 - 支持 4 种连接方式"""
import json
import re
import os
import logging
from datetime import datetime
from typing import AsyncGenerator


QUIZ_BLOCK_INSTRUCTION = """
7. **交互式出题规则（重要）**：当你要给学生出练习题/测验题时，**必须**在题目部分使用 QUIZ_BLOCK 标记输出结构化题目数据，前端会自动渲染为交互式答题卡片：
   <!--QUIZ_BLOCK:[{{"id":1,"type":"choice","question":"题面（数学公式用LaTeX $...$）","options":["A. 选项1","B. 选项2","C. 选项3","D. 选项4"],"answer":"A","knowledge_point":"关联知识点","difficulty":"easy/medium/hard","hint":"可选的解题提示"}},{{"id":2,"type":"fill","question":"计算 $3+5=$ ____","answer":"8","knowledge_point":"关联知识点","difficulty":"easy","hint":""}},{{"id":3,"type":"short_answer","question":"简述有理数的定义","answer":"有理数是整数和分数的统称","knowledge_point":"关联知识点","difficulty":"medium","hint":""}}]-->
   
   题目类型说明：
   - `choice`：选择题（单选），必须提供 options 数组和正确答案字母（如 "A"）
   - `fill`：填空题，题面中用 `____` 表示空位，answer 为标准答案
   - `short_answer`：简答题/计算题，answer 为参考答案
   
   注意：
   - 每道题必须有唯一递增的 id（1, 2, 3...）
   - 出题时在 QUIZ_BLOCK 标记**之前**可以写一些引导语（如"让我们来做几道练习"）
   - QUIZ_BLOCK 标记**之后**不要再重复写题目的文字版本，前端会自动渲染
   - 选择题的 options 必须带字母前缀（如 "A. xxx"），answer 只写字母
   - 数学公式在 question 和 options 中都可以使用 $...$ LaTeX 格式
   - hint 字段可选，空字符串表示无提示"""

QUESTION_RECORD_INSTRUCTION = """
8. **题目记录规则（极其重要！必须执行！）**：当你在本轮回复中**批改了学生的练习答案**（无论对错），你**必须**在回复末尾添加 QUESTION_RECORD 标记。这是系统记录错题和学习数据的唯一途径，遗漏会导致学习档案数据缺失！
   格式：<!--QUESTION_RECORD:[{{"question":"题面（含必要条件，数学用LaTeX）","student_answer":"学生的答案","correct_answer":"正确答案","is_correct":true/false,"knowledge_point":"关联知识点名","difficulty":"easy/medium/hard","error_analysis":"错因简析（仅错题需要，正确题留空）"}}]-->
   **执行检查清单**：
   - ✅ 你批改了学生的答案 → **必须**添加 QUESTION_RECORD
   - ✅ 学生回答了你出的选择题/填空题/问答题 → **必须**添加 QUESTION_RECORD
   - ✅ 一次批改多道题 → 在一个 QUESTION_RECORD 数组中记录**所有**题目
   - ❌ 你刚出题等待学生回答 → 不要记录，等学生答完再记
   - ❌ 纯概念讲解没有题目 → 不需要记录
   注意：
   - 题面要精简完整，能独立看懂，但不要超过 200 字
   - knowledge_point 必须与 KNOWLEDGE_UPDATE 中使用的知识点名称一致
   - error_analysis 要简洁指出错误类型（如"符号搞混"、"公式记错"、"计算粗心"），不超过 50 字"""

REFERENCE_USAGE_INSTRUCTION = """
**参考资料使用规范**：
1. 上面的参考资料是教师上传的教材、讲义等，其中的内容是教学的核心依据
2. 讲解知识点时优先参考这些资料中的定义、公式、例题和教学思路
3. **但参考资料可能不完整**——它们只是教材的部分内容，可能缺少某些知识点的详细解释、补充例题或拓展内容
4. 当你发现参考资料中的内容不足以完整教学（比如缺少某公式的推导过程、没有足够的例题、缺少某个概念的直观解释）时：
   - 如果你有 Google Search 工具，应主动搜索权威教学资源来补充不足之处
   - 搜索时使用精确的学科术语，优先查找教育类网站的内容
   - 将搜索到的补充内容自然融入教学中，不要生硬地说"我搜索到了..."
5. 即使没有搜索工具，也应该利用你自身的知识来补充参考资料的不足，确保教学完整性
"""

SYSTEM_PROMPT_NORMAL = """你是 EduChat 的 AI 教学助手，一位耐心、专业、有趣的老师。你正在辅导一位学生的{course_name}课程。
{custom_instruction_block}
## 学生记忆档案
{memory_context}

## 参考资料上下文
{reference_context}
""" + REFERENCE_USAGE_INSTRUCTION + """
## 教学流程规范（必须遵守）
每次讲解一个知识点时，必须遵循以下完整教学流程：

**第一阶段：讲解**
- 清晰讲解知识点的核心概念、公式、方法
- 配合 1-2 个典型例题进行演示

**第二阶段：出练习题（必须！）**
- 讲解完成后，**必须**在同一条回复的末尾出 2-3 道针对性练习题
- 题目要覆盖刚讲的知识点，由易到难梯度设置
- 明确告诉学生"请尝试做一下这几道题"，然后**等待学生回答**
- 此时 interaction_type 标记为 "taught"（因为学生还没作答）

**第三阶段：批改与评价**
- 学生提交答案后，逐题批改、给出对错反馈和解析
- 根据做题结果评估 comprehension，此时 interaction_type 标记为 "practiced"
- 如果学生做错了，引导纠正后标记 "corrected"

**重要**：不要跳过第二阶段！纯讲解不出题 = 无法评估掌握度 = taught 不计入 mastery。只有走完出题→作答→批改的闭环，才能真正评估和记录学生的掌握情况。

## 指令
1. 基于学生的学习进度和记忆档案进行个性化教学
2. **知识点更新规则（非常重要）**：
   - 只有当你在本次对话中**实际讲解、教学、练习了某个知识点**时，才在回复末尾添加 KNOWLEDGE_UPDATE 标记
   - **严禁**在制定学习计划、列举课程大纲、讨论学习目标时把仅仅"提到"的知识点也加入标记
   - 简言之：没教过 = 不标记，教了才标记
   - interaction_type 说明（请严格区分！）：
     - "taught": 你讲解了知识点并出了练习题，但**学生尚未作答**。注意：taught 类型**不会增加任何掌握度**，仅作为学习记录
     - "assessed": 你通过**问答互动**确认了学生的理解程度（学生回答了概念性问题、复述了要点等），但还没做正式练习题
     - "practiced": 学生做了**练习题**并且你已经**批改给出了对错反馈**
     - "corrected": 学生针对之前做错的题进行了纠错订正
   - comprehension 由你根据学生的理解表现评分（0-100），反映学生是否听懂、能否举一反三
   - questions_total / questions_correct 仅在 practiced/tested/corrected 时提供
   格式：<!--KNOWLEDGE_UPDATE:[{{"name":"知识点名","chapter":"所属章节","difficulty":"easy/medium/hard","interaction_type":"taught/assessed/practiced/corrected","comprehension":0-100,"questions_total":3,"questions_correct":2}}]-->
3. **记忆更新规则**：当需要更新学生记忆时，在回复末尾添加标记：
   <!--MEMORY_UPDATE:{{"field_path":"字段路径","value":"新值"}}-->
   可多次使用。常用字段路径：
   - `student_profile.learning_style`：学习风格描述（如"善于通过例子理解概念"、"偏好先看公式推导再做题"等）
   - `student_profile.difficulty_preference`：难度偏好，可选值 easy/medium/medium-hard/hard
   - `student_profile.notes`：学生特点备注（如"计算容易粗心"、"逻辑推理能力强但计算偏弱"等）
   **student_profile 更新时机（极其重要！必须执行！）**：
   - **如果 student_profile 的 learning_style 或 notes 为空，你必须在第 1-2 轮教学互动后就根据观察填写，不要拖延！**
   - 当你批改练习/作业后，**必须**在同一条回复中通过 MEMORY_UPDATE 更新 student_profile.notes，总结该学生的能力特征
   - 每次批改后，根据学生的对错表现补充或更新 notes（如"概念理解较好但时间复杂度分析薄弱"、"计算类题目容易粗心"等）
   - 每 3-5 轮有效教学互动后，检查 student_profile 是否需要更新或补充
   - learning_style 示例："善于通过具体例子理解抽象概念"、"偏好先看代码再理解原理"、"喜欢类比式教学"
   - `teaching_plan.goals`：教学目标列表，如 ["掌握有理数运算","理解一元一次方程"]
   - `teaching_plan.direction`：简要的计划方向说明
   - `teaching_plan.steps`：教学步骤列表，**每个步骤必须为对象格式**：
     [{{"title":"步骤名","linked_kps":["关联知识点1","关联知识点2"],"mastery_threshold":60,"status":"not_started"}}]
     · `linked_kps`：该步骤关联的**细粒度知识点名称**。你可以自由命名，系统会自动创建不存在的知识点。
       命名原则：按教学实际粒度拆分，如"有理数的加减法"、"有理数的乘除法"、"有理数的乘方"，而非笼统的"有理数"
     · `mastery_threshold`：达标阈值（默认60，难的步骤可设70-80）
     · `status`：初始设为 "not_started"，系统会根据知识点 mastery 自动推进
   **教学计划更新时机**：
   - 首次与学生讨论学习规划时 → 生成 goals + steps + direction
   - 学生要求调整计划或发现计划不合理时 → 重新生成 steps
   - 注意：**不需要手动更新 current_step 和 status**，系统会根据「教学完成标记 + 知识点 mastery」双条件自动推进
   **步骤达标条件（双条件）**：
   - 条件1：你通过 STEP_COMPLETE 标记确认该步骤教学内容已充分完成
   - 条件2：该步骤关联的所有知识点 mastery 达到阈值（系统自动计算）
   - 两个条件都满足后，系统自动将步骤标记为 mastered
   **教学计划制定原则**：
   - 按照教材章节和知识体系，制定**细致、合理**的分步教学计划
   - 可以分阶段（如"第一阶段：有理数运算"下拆分多个步骤），步骤总数建议 10-20 步
   - 每个步骤对应 1-2 个细粒度知识点，知识点名称要具体（如"有理数的加减法"而非"有理数"）
   - 后续教学中用 KNOWLEDGE_UPDATE 标记更新的知识点 name **必须与** steps 中 linked_kps 里的名称一致，这样系统才能自动推进进度
4. 使用 Markdown 格式回复，数学公式使用 LaTeX（$行内$ 或 $$块级$$）
5. 保持友善鼓励的教学风格，适当使用类比和例子
6. **步骤教学完成标记（重要）**：当你完成了某个教学步骤的**完整教学流程**（概念讲解 → 出练习题 → 学生作答 → 批改反馈），确认该步骤的教学内容已经充分、全面地完成时，在回复末尾添加：
   <!--STEP_COMPLETE:{{"step_title":"步骤标题"}}-->
   注意：
   - **只有完成了完整的教学闭环才能标记**，仅讲解了概念但还没出题/批改不算完成
   - **绝对禁止在出练习题的同一条回复中添加 STEP_COMPLETE 标记！** 你必须等学生提交答案、你完成批改反馈之后，才能在批改反馈的那条回复中添加 STEP_COMPLETE
   - 正确的流程是：讲解概念 → 出练习题（这条回复**不能**有 STEP_COMPLETE）→ 等学生作答 → 批改反馈（如果学生都答对了，这条回复**才可以**添加 STEP_COMPLETE）
   - 如果学生答错了较多题目，应该补充讲解后再出题验证，不能标记完成
   - 步骤标题必须与 teaching_plan.steps 中的 title 完全一致
   - 一个步骤可能涉及多个知识点，所有知识点都教完且有互动验证后才标记
   - 步骤最终达标需要同时满足：教学完成（此标记）+ 知识点掌握度达标（系统自动判定）""" + QUIZ_BLOCK_INSTRUCTION + QUESTION_RECORD_INSTRUCTION

SYSTEM_PROMPT_HOMEWORK = """你是 EduChat 的 AI 作业批改助手。你正在帮助学生检查{course_name}的作业。
{custom_instruction_block}
## 学生记忆档案
{memory_context}

## 参考资料上下文
{reference_context}
""" + REFERENCE_USAGE_INSTRUCTION + """
## 指令
1. 仔细检查学生提交的作业（可能是图片或文字）
2. 逐题批改，标明对错，给出详细解析
3. 在回复末尾添加作业结果标记（注意 knowledge_scores 按知识点统计逐题数据）：
   <!--HOMEWORK_RESULT:{{"total_questions":数量,"correct":正确数,"score":百分制分数,"weak_points":["薄弱知识点"],"feedback":"总评","knowledge_scores":[{{"name":"知识点名","questions_total":该知识点总题数,"questions_correct":该知识点做对题数}}]}}-->
4. 根据作业表现更新相关知识点的 KNOWLEDGE_UPDATE 标记：
   - interaction_type 使用 "tested"
   - comprehension 反映学生在作业中展现的理解程度
   - questions_total / questions_correct 为该知识点涉及的题数和做对题数
   格式：<!--KNOWLEDGE_UPDATE:[{{"name":"知识点名","chapter":"所属章节","difficulty":"easy/medium/hard","interaction_type":"tested","comprehension":0-100,"questions_total":3,"questions_correct":2}}]-->
5. 语气鼓励但专业，指出错误时同时给出正确思路
6. **题目记录（重要）**：对作业中的**每一道题**都必须添加 QUESTION_RECORD 标记，完整记录题面、学生答案、正确答案和对错：
   <!--QUESTION_RECORD:[{{"question":"题面","student_answer":"学生答案","correct_answer":"正确答案","is_correct":true/false,"knowledge_point":"关联知识点名","difficulty":"easy/medium/hard","error_analysis":"错因简析（仅错题）"}}]-->
   注意：作业中每道题都要记录，不论对错"""

SYSTEM_PROMPT_EXAM = """你是 EduChat 的 AI 考试分析助手。你正在帮助学生分析{course_name}的考试。
{custom_instruction_block}
## 学生记忆档案
{memory_context}

## 参考资料上下文
{reference_context}
""" + REFERENCE_USAGE_INSTRUCTION + """
## 指令
1. 分析学生上传的考卷（可能是图片或文字）
2. 逐题分析：题目→学生答案→正确答案→知识点→掌握程度评估
3. 在回复末尾添加考试结果标记（注意 knowledge_scores 按知识点统计逐题数据）：
   <!--EXAM_RESULT:{{"total_score":总分,"student_score":得分,"weak_topics":["薄弱主题"],"strong_topics":["强项主题"],"recommendations":["建议"],"knowledge_scores":[{{"name":"知识点名","questions_total":该知识点总题数,"questions_correct":该知识点做对题数}}]}}-->
4. 自动生成 2-3 道针对薄弱点的练习题
5. 根据考试表现添加 KNOWLEDGE_UPDATE 标记更新知识点：
   - interaction_type 使用 "tested"
   - comprehension 反映学生在考试中展现的理解程度
   - questions_total / questions_correct 为该知识点涉及的题数和做对题数
   格式：<!--KNOWLEDGE_UPDATE:[{{"name":"知识点名","chapter":"所属章节","difficulty":"easy/medium/hard","interaction_type":"tested","comprehension":0-100,"questions_total":3,"questions_correct":2}}]-->
6. **题目记录（重要）**：对考卷中的**每一道题**都必须添加 QUESTION_RECORD 标记，完整记录：
   <!--QUESTION_RECORD:[{{"question":"题面","student_answer":"学生答案","correct_answer":"正确答案","is_correct":true/false,"knowledge_point":"关联知识点名","difficulty":"easy/medium/hard","error_analysis":"错因简析（仅错题）"}}]-->
   注意：考试中每道题都要记录，不论对错"""

SYSTEM_PROMPT_REVIEW = """你是 EduChat 的 AI 复习导师。你正在帮助学生对{course_name}的知识点「{review_point}」进行针对性复习。
{custom_instruction_block}
## 学生记忆档案
{memory_context}

## 该知识点详细档案
{review_context}

## 该知识点历史错题（变式出题参考）
{wrong_questions_context}

## 参考资料上下文
{reference_context}
""" + REFERENCE_USAGE_INSTRUCTION + """
## 复习策略指令
根据该知识点的掌握情况，你需要自主选择最合适的复习策略：

### 策略选择依据
- **掌握度 ≥ 80%**：快速确认式复习 — 提 1-2 个关键问题确认记忆，答对则简短总结结束
- **掌握度 50-79%**：针对性强化 — 先快速回顾核心概念，然后出 2-3 道针对薄弱环节的练习题
- **掌握度 < 50%**：系统性重学 — 重新讲解该知识点的核心概念，配合例题，再出练习题巩固

### 利用历史错题
- 如果上面有历史错题数据，**必须参考这些错题来设计复习内容**
- 出的练习题应该是错题的**变式题**（改变数值、调整条件、变换问法），而不是原题照搬
- 针对错因分析中指出的薄弱点重点强化
- 如果没有错题数据，则按常规策略出题

### 复习流程
1. 先简要告诉学生这次复习的目标和策略（1-2 句话）
2. 根据上述策略执行复习内容
3. 在复习过程中，通过问答互动评估学生的实际记忆程度
4. 复习结束时，在回复末尾添加复习完成标记：
   <!--REVIEW_COMPLETE:{{"quality":0-5,"summary":"复习总结"}}-->
   quality 评分标准：0=完全忘记 1=几乎忘记 2=依稀记得 3=需要提示才想起 4=基本记住 5=完美回忆
5. 同时添加 KNOWLEDGE_UPDATE 标记更新该知识点：
   - interaction_type 根据实际情况选择 "assessed"(通过问答确认了理解) 或 "practiced"(做了练习题)。复习中必定有互动，所以**不要用 "taught"**
   - comprehension 反映学生在复习中展现的理解程度
   格式：<!--KNOWLEDGE_UPDATE:[{{"name":"{review_point}","chapter":"所属章节","difficulty":"easy/medium/hard","interaction_type":"assessed/practiced","comprehension":0-100,"questions_total":题数,"questions_correct":正确数}}]-->

### 题目记录
- 复习中出的练习题和学生的作答结果也要记录：
  <!--QUESTION_RECORD:[{{"question":"题面","student_answer":"学生答案","correct_answer":"正确答案","is_correct":true/false,"knowledge_point":"{review_point}","difficulty":"easy/medium/hard","error_analysis":"错因简析（仅错题）"}}]-->
- 注意：仅在学生**实际作答后**才记录，刚出题等待回复时不记录

### 重要注意
- 不要在第一条消息就添加 REVIEW_COMPLETE 标记，要等复习对话真正结束后才添加
- 保持友善鼓励的语气，复习不是考试，是帮助巩固记忆
- 使用 Markdown 格式，数学公式使用 LaTeX（$行内$ 或 $$块级$$）
- 出练习题时**必须**使用 QUIZ_BLOCK 标记输出结构化题目（同普通教学模式的交互式出题规则）
- 第一条消息就直接开始复习，不要问学生"准备好了吗"之类的废话"""


def _build_memory_context(memory: dict) -> str:
    parts = []
    ci = memory.get("course_info", {})
    if ci.get("name"):
        parts.append(f"课程: {ci['name']}")
    lp = memory.get("learning_progress", {})
    if lp.get("current_topic"):
        parts.append(f"当前学习主题: {lp['current_topic']}")
    if lp.get("mastery_level"):
        parts.append(f"整体掌握度: {lp['mastery_level']}%")
    tp = memory.get("teaching_plan", {})
    if tp.get("steps"):
        step_idx = tp.get("current_step", 0)
        step_lines = []
        for i, s in enumerate(tp["steps"]):
            if isinstance(s, dict):
                title = s.get("title", "?")
                status = s.get("status", "not_started")
                linked = s.get("linked_kps", [])
                threshold = s.get("mastery_threshold", 60)
                status_icon = {"mastered": "✓", "in_progress": "→", "needs_review": "⚠", "not_started": "○"}.get(status, "○")
                line = f"  {status_icon} {title}"
                if linked:
                    # 查找关联知识点的 mastery
                    kp_map_tmp = {kp.get("name"): kp for kp in memory.get("knowledge_points", [])}
                    kp_info = []
                    for kn in linked:
                        m_val = kp_map_tmp.get(kn, {}).get("mastery", 0)
                        kp_info.append(f"{kn}:{m_val}%")
                    line += f" [{', '.join(kp_info)}, 达标线{threshold}%]"
                step_lines.append(line)
            else:
                icon = '✓' if i < step_idx else '→' if i == step_idx else '○'
                step_lines.append(f"  {icon} {s}")
        parts.append(f"教学计划:\n" + "\n".join(step_lines))
    kps = memory.get("knowledge_points", [])
    if kps:
        kp_parts = []
        for p in kps[:15]:
            name = p.get("name", "?")
            mastery = p.get("mastery", 0)
            comp = p.get("comprehension", 0)
            pt = p.get("practice_total", 0)
            pc = p.get("practice_correct", 0)
            chapter = p.get("chapter", "")
            detail = f"{name}(掌握{mastery}%, 理解{comp}"
            if pt > 0:
                detail += f", 练习{pc}/{pt}题"
            if chapter:
                detail += f", {chapter}"
            detail += ")"
            kp_parts.append(detail)
        parts.append(f"知识点掌握: {', '.join(kp_parts)}")
    sp = memory.get("student_profile", {})
    sp_parts = []
    if sp.get("learning_style"):
        sp_parts.append(f"学习风格: {sp['learning_style']}")
    if sp.get("difficulty_preference") and sp["difficulty_preference"] != "medium":
        pref_map = {"easy": "偏简单", "medium": "适中", "medium-hard": "中等偏难", "hard": "偏难"}
        sp_parts.append(f"难度偏好: {pref_map.get(sp['difficulty_preference'], sp['difficulty_preference'])}")
    if sp.get("notes"):
        sp_parts.append(f"学生特点: {sp['notes']}")
    if sp_parts:
        parts.append("学生画像: " + "; ".join(sp_parts))
    elif not sp.get("learning_style") and not sp.get("notes"):
        parts.append("学生画像: 尚未建立（请在教学互动中观察并通过 MEMORY_UPDATE 更新 student_profile）")
    qa = memory.get("quiz_analysis", {})
    if qa.get("weaknesses"):
        parts.append(f"薄弱环节: {', '.join(qa['weaknesses'])}")
    prior = memory.get("prior_knowledge")
    if prior:
        parts.append("--- 先修知识档案 ---")
        parts.append(prior.get("summary", ""))
        parts.append("请注意: 学生已有先修课程积累的知识基础。对学生已掌握的先修知识可适当跳过基础讲解，"
                      "对薄弱环节需重点关注。新课程的知识点将从零积累，但教学起点应参考上述先修能力。")
    return "\n".join(parts) if parts else "暂无记忆数据"


def _build_review_context(memory: dict, point_name: str) -> str:
    """为复习模式构建单个知识点的详细上下文"""
    kps = memory.get("knowledge_points", [])
    kp = None
    for p in kps:
        if p.get("name") == point_name:
            kp = p
            break
    if not kp:
        return f"知识点「{point_name}」暂无详细数据"

    parts = [f"知识点: {kp.get('name', '')}"]
    if kp.get("chapter"):
        parts.append(f"所属章节: {kp['chapter']}")
    if kp.get("difficulty"):
        parts.append(f"难度: {kp['difficulty']}")
    parts.append(f"综合掌握度 (mastery): {kp.get('mastery', 0)}%")
    parts.append(f"理解度 (comprehension): {kp.get('comprehension', 0)}%")

    pt, pc = kp.get("practice_total", 0), kp.get("practice_correct", 0)
    if pt > 0:
        parts.append(f"AI练习记录: {pc}/{pt} 题正确 ({round(pc/pt*100)}%)")

    tt, tc = kp.get("test_total", 0), kp.get("test_correct", 0)
    if tt > 0:
        parts.append(f"作业/考试记录: {tc:.1f}/{tt} 题正确 ({round(tc/tt*100)}%)")
    else:
        # 兼容旧数据
        tsh = kp.get("test_score_history", [])
        if tsh:
            parts.append(f"考试/作业得分历史 (最近{len(tsh)}次): {', '.join(str(s) for s in tsh)}")

    rqh = kp.get("review_quality_history", [])
    if rqh:
        parts.append(f"复习质量历史 (最近{len(rqh)}次, 0-5): {', '.join(str(q) for q in rqh)}")

    tier = kp.get("review_tier", "")
    if tier:
        tier_label = "SM-2 间隔递增" if tier == "sm2" else "固定5天巩固" if tier == "consolidation" else tier
        parts.append(f"当前复习层级: {tier_label}")

    if kp.get("sm2_interval"):
        parts.append(f"SM-2 当前间隔: {kp['sm2_interval']} 天")
    if kp.get("sm2_easiness"):
        parts.append(f"SM-2 难度因子: {kp['sm2_easiness']:.2f}")

    # 查看最近的作业/考试记录中是否有该知识点的表现
    hw_records = memory.get("homework_history", [])
    exam_records = memory.get("exam_history", [])
    related_records = []
    for rec in (hw_records + exam_records)[-5:]:
        ks = rec.get("knowledge_scores", [])
        for k in ks:
            if k.get("name") == point_name:
                rec_type = "作业" if rec in hw_records else "考试"
                related_records.append(f"{rec_type}得分率: {k.get('score_rate', '?')}%")
    if related_records:
        parts.append(f"近期作业/考试表现: {'; '.join(related_records)}")

    return "\n".join(parts)


def _build_wrong_questions_context(wrong_questions: list) -> str:
    """将精选错题列表格式化为上下文文本"""
    if not wrong_questions:
        return "暂无该知识点的历史错题记录"

    parts = [f"共 {len(wrong_questions)} 道历史错题："]
    for i, q in enumerate(wrong_questions, 1):
        lines = [f"错题{i}: {q.get('question', '?')}"]
        if q.get("student_answer"):
            lines.append(f"  学生答案: {q['student_answer']}")
        if q.get("correct_answer"):
            lines.append(f"  正确答案: {q['correct_answer']}")
        if q.get("error_analysis"):
            lines.append(f"  错因: {q['error_analysis']}")
        if q.get("difficulty"):
            lines.append(f"  难度: {q['difficulty']}")
        if q.get("source"):
            source_label = {"homework": "作业", "exam": "考试", "practice": "练习", "review": "复习"}.get(q["source"], q["source"])
            lines.append(f"  来源: {source_label}")
        parts.append("\n".join(lines))

    return "\n\n".join(parts)


class ChatService:
    async def _get_client(self, gemini_config: dict):
        mode = gemini_config.get("connection_mode", "ai_studio")
        model = gemini_config.get("model", "gemini-2.5-flash")

        if mode == "ai_studio":
            from google import genai
            client = genai.Client(api_key=gemini_config.get("api_key", ""))
            return ("genai", client, model)

        elif mode == "vertex_ai":
            from google import genai
            client = genai.Client(
                vertexai=True,
                project=gemini_config.get("vertex_project", ""),
                location=gemini_config.get("vertex_location", "us-central1"),
            )
            return ("genai", client, model)

        elif mode == "openai_compat":
            from openai import AsyncOpenAI
            client = AsyncOpenAI(
                api_key=gemini_config.get("openai_api_key", "") or gemini_config.get("api_key", ""),
                base_url=gemini_config.get("openai_base_url", "https://generativelanguage.googleapis.com/v1beta/openai/"),
            )
            return ("openai", client, model)

        elif mode == "custom_endpoint":
            backend = gemini_config.get("custom_backend", "openai")
            if backend == "openai":
                from openai import AsyncOpenAI
                client = AsyncOpenAI(
                    api_key=gemini_config.get("custom_api_key", ""),
                    base_url=gemini_config.get("custom_base_url", ""),
                )
                return ("openai", client, model)
            else:
                from google import genai
                custom_url = gemini_config.get("custom_base_url", "")
                os.environ["GOOGLE_API_BASE"] = custom_url
                client = genai.Client(api_key=gemini_config.get("custom_api_key", ""))
                return ("genai", client, model)

        raise ValueError(f"Unknown connection mode: {mode}")

    async def test_connection(self, gemini_config: dict) -> dict:
        try:
            backend_type, client, model = await self._get_client(gemini_config)
            if backend_type == "genai":
                response = client.models.generate_content(
                    model=model,
                    contents="Say 'connected' in one word."
                )
                return {"success": True, "message": "连接成功", "response": response.text[:50]}
            else:
                response = await client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": "Say 'connected' in one word."}],
                    max_tokens=10,
                )
                return {"success": True, "message": "连接成功", "response": response.choices[0].message.content[:50]}
        except Exception as e:
            return {"success": False, "message": f"连接失败: {str(e)}"}

    async def stream_chat(
        self,
        gemini_config: dict,
        memory: dict,
        messages: list,
        mode: str = "normal",
        reference_context: str = "",
        file_parts: list = None,
        review_point: str = "",
        wrong_questions_context: str = "",
    ) -> AsyncGenerator[str, None]:
        course_name = memory.get("course_info", {}).get("name", "未知课程")
        memory_context = _build_memory_context(memory)

        # 构建自定义指令块
        custom_instruction = memory.get("course_info", {}).get("description", "").strip()
        custom_instruction_block = ""
        if custom_instruction:
            custom_instruction_block = f"\n## 用户自定义指令（必须遵守）\n{custom_instruction}\n"

        if mode == "homework_check":
            sys_prompt = SYSTEM_PROMPT_HOMEWORK
        elif mode == "exam_analysis":
            sys_prompt = SYSTEM_PROMPT_EXAM
        elif mode == "review" and review_point:
            sys_prompt = SYSTEM_PROMPT_REVIEW
            review_context = _build_review_context(memory, review_point)
            sys_prompt = sys_prompt.format(
                course_name=course_name,
                custom_instruction_block=custom_instruction_block,
                memory_context=memory_context,
                reference_context=reference_context or "无参考资料",
                review_point=review_point,
                review_context=review_context,
                wrong_questions_context=wrong_questions_context or "暂无该知识点的历史错题记录",
            )
        else:
            sys_prompt = SYSTEM_PROMPT_NORMAL

        if mode != "review" or not review_point:
            sys_prompt = sys_prompt.format(
                course_name=course_name,
                custom_instruction_block=custom_instruction_block,
                memory_context=memory_context,
                reference_context=reference_context or "无参考资料",
            )

        backend_type, client, model = await self._get_client(gemini_config)
        active_tools = gemini_config.get("tools", [])

        if backend_type == "genai":
            async for chunk in self._stream_genai(client, model, sys_prompt, messages, file_parts, active_tools):
                yield chunk
        else:
            async for chunk in self._stream_openai(client, model, sys_prompt, messages):
                yield chunk

    async def _stream_genai(self, client, model, sys_prompt, messages, file_parts=None, active_tools=None):
        from google.genai import types
        contents = []
        for msg in messages:
            role = "user" if msg["role"] == "user" else "model"
            contents.append(types.Content(role=role, parts=[types.Part.from_text(text=msg["content"])]))

        if file_parts and contents:
            last_parts = list(contents[-1].parts)
            for fp in file_parts:
                last_parts.append(fp)
            contents[-1] = types.Content(role=contents[-1].role, parts=last_parts)

        # Build tools list
        genai_tools = []
        if active_tools:
            if "google_search" in active_tools:
                genai_tools.append(types.Tool(google_search=types.GoogleSearch()))
            if "code_execution" in active_tools:
                genai_tools.append(types.Tool(code_execution=types.ToolCodeExecution()))
            if "url_context" in active_tools:
                genai_tools.append(types.Tool(url_context=types.UrlContext()))

        try:
            config_kwargs = {
                "system_instruction": sys_prompt,
                "temperature": 0.7,
                "max_output_tokens": 8192,
            }
            if genai_tools:
                config_kwargs["tools"] = genai_tools

            response = client.models.generate_content_stream(
                model=model,
                contents=contents,
                config=types.GenerateContentConfig(**config_kwargs),
            )
            for chunk in response:
                # 遍历所有 parts，提取代码执行、搜索结果等特殊内容
                if chunk.candidates:
                    for candidate in chunk.candidates:
                        if not candidate.content or not candidate.content.parts:
                            continue
                        for part in candidate.content.parts:
                            if part.text:
                                yield part.text
                            elif part.executable_code:
                                code = part.executable_code.code or ""
                                lang = (part.executable_code.language or "PYTHON").lower()
                                # 以特殊 Markdown 块输出，前端可识别渲染
                                yield f"\n\n```exec_{lang}\n{code}\n```\n\n"
                            elif part.code_execution_result:
                                output = part.code_execution_result.output or ""
                                outcome = part.code_execution_result.outcome or "OUTCOME_OK"
                                if str(outcome).endswith("OK") or str(outcome) == "1":
                                    yield f"\n\n```exec_output\n{output}\n```\n\n"
                                else:
                                    yield f"\n\n```exec_error\n{output}\n```\n\n"
                elif chunk.text:
                    yield chunk.text
        except Exception as e:
            raise RuntimeError(f"AI 响应错误: {str(e)}") from e

    async def _stream_openai(self, client, model, sys_prompt, messages):
        oai_messages = [{"role": "system", "content": sys_prompt}]
        for msg in messages:
            oai_messages.append({"role": msg["role"], "content": msg["content"]})

        try:
            stream = await client.chat.completions.create(
                model=model,
                messages=oai_messages,
                stream=True,
                temperature=0.7,
                max_tokens=8192,
            )
            async for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
        except Exception as e:
            raise RuntimeError(f"AI 响应错误: {str(e)}") from e

    def parse_ai_response(self, full_response: str) -> dict:
        result = {
            "clean_text": full_response,
            "knowledge_updates": [],
            "memory_updates": [],
            "homework_result": None,
            "exam_result": None,
            "review_complete": None,
            "question_records": [],
            "step_completes": [],
            "quiz_blocks": [],
        }

        ku_match = re.search(r'<!--KNOWLEDGE_UPDATE:(\[.*?\])-->', full_response, re.DOTALL)
        if ku_match:
            try:
                result["knowledge_updates"] = json.loads(ku_match.group(1))
            except json.JSONDecodeError:
                pass
            result["clean_text"] = result["clean_text"].replace(ku_match.group(0), "").strip()

        mu_pattern = re.finditer(r'<!--MEMORY_UPDATE:(\{.*?\})-->', full_response, re.DOTALL)
        for m in mu_pattern:
            try:
                result["memory_updates"].append(json.loads(m.group(1)))
            except json.JSONDecodeError:
                pass
            result["clean_text"] = result["clean_text"].replace(m.group(0), "").strip()

        hw_match = re.search(r'<!--HOMEWORK_RESULT:(\{.*?\})-->', full_response, re.DOTALL)
        if hw_match:
            try:
                result["homework_result"] = json.loads(hw_match.group(1))
            except json.JSONDecodeError:
                pass
            result["clean_text"] = result["clean_text"].replace(hw_match.group(0), "").strip()

        ex_match = re.search(r'<!--EXAM_RESULT:(\{.*?\})-->', full_response, re.DOTALL)
        if ex_match:
            try:
                result["exam_result"] = json.loads(ex_match.group(1))
            except json.JSONDecodeError:
                pass
            result["clean_text"] = result["clean_text"].replace(ex_match.group(0), "").strip()

        rc_match = re.search(r'<!--REVIEW_COMPLETE:(\{.*?\})-->', full_response, re.DOTALL)
        if rc_match:
            try:
                result["review_complete"] = json.loads(rc_match.group(1))
            except json.JSONDecodeError:
                pass
            result["clean_text"] = result["clean_text"].replace(rc_match.group(0), "").strip()

        qr_match = re.search(r'<!--QUESTION_RECORD:(\[.*?\])-->', full_response, re.DOTALL)
        if qr_match:
            try:
                result["question_records"] = json.loads(qr_match.group(1))
            except json.JSONDecodeError:
                pass
            result["clean_text"] = result["clean_text"].replace(qr_match.group(0), "").strip()

        sc_pattern = re.finditer(r'<!--STEP_COMPLETE:(\{.*?\})-->', full_response, re.DOTALL)
        for sc in sc_pattern:
            try:
                result["step_completes"].append(json.loads(sc.group(1)))
            except json.JSONDecodeError:
                pass
            result["clean_text"] = result["clean_text"].replace(sc.group(0), "").strip()

        # QUIZ_BLOCK: replace with ```quiz_block JSON``` so frontend can render interactive cards
        # Also kept in clean_text for history loading
        qb_match = re.search(r'<!--QUIZ_BLOCK:(\[.*?\])-->', full_response, re.DOTALL)
        if qb_match:
            try:
                quiz_data = json.loads(qb_match.group(1))
                result["quiz_blocks"] = quiz_data
                # Replace the HTML comment with a code block the frontend recognizes
                quiz_json_str = json.dumps(quiz_data, ensure_ascii=False)
                result["clean_text"] = result["clean_text"].replace(
                    qb_match.group(0),
                    f"\n\n```quiz_block\n{quiz_json_str}\n```\n\n"
                ).strip()
            except json.JSONDecodeError:
                pass

        # Guard: if this response contains quiz blocks, discard step_completes
        # AI should not mark step complete in the same message as issuing a quiz
        if result["quiz_blocks"] and result["step_completes"]:
            logger.warning(f"AI incorrectly marked STEP_COMPLETE in same message as QUIZ_BLOCK, discarding step_completes: {result['step_completes']}")
            result["step_completes"] = []

        return result


chat_service = ChatService()
