# -*- coding: utf-8 -*-
"""AI 回复建议引擎（OpenAI 兼容接口，默认 DeepSeek）。

- 零第三方依赖（仅标准库 urllib），保证 exe 体积不膨胀；
- 每个聊天对象一个「会话」：第一次请求把全部历史打包给 AI，之后沿用同一会话上下文；
- 上下文自动滚动窗口：token 超出预算时丢弃最旧消息，保持后续对话连续；
- 触发：对方新消息到达时自动生成「下一句」建议。
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.error
import urllib.request

DEFAULT_CONFIG = {
    "api_url": "https://inferaiapi.com/v1/chat/completions",
    "api_key": "",
    "model": "mimo-v2.6-pro",
    "enabled": False,
    "trigger_on_peer": True,   # 对方新消息自动出建议
    "auto_copy": False,        # 收到新消息把建议自动放进剪贴板
    "max_context_msgs": 80,    # 后续滚动窗口
    "first_ctx_msgs": 500,     # 首次全量喂入条数上限
    "persona": "",             # 人格底色：用户自定义想让 AI 扮演的自己（如：幽默毒舌、温柔靠谱）
    "analysis_task": "",        # 自定义分析指令：用户想重点看什么（留空用默认任务书）
    "prompt": (
        "你是我的聊天教练，帮我学会跟异性聊天、撩妹、谈恋爱。我会给你我和对方的聊天历史，"
        "请站在【我】的角度，给出3个不同风格的下一句回复方案，并分别讲解思路。\n"
        "要求：\n"
        "1. A｜{方案A：温和稳妥，安全不踩雷}\n理由｜{为什么这么说，1-2句}\n"
        "2. B｜{方案B：幽默俏皮，带点趣味}\n理由｜{1-2句}\n"
        "3. C｜{方案C：直球推进，升温关系}\n理由｜{1-2句}\n"
        "必须严格按照上面格式输出，不要额外内容；每句回复不超过30字；"
        "贴合上下文和对方此刻的情绪；站在我的角度、用自然口语化的中文。"
    ),
}

# 预设模型列表（inferaiapi 网关 /v1/models 实测可用），设置面板下拉直接选
PRESET_MODELS = [
    "mimo-v2.6-pro",
    "mimo-v2.6",
    "mimo-v2.5-pro",
    "mimo-v2.5",
    "deepseek-v4-pro",
    "deepseek-v4-flash",
    "deepseek-v4.1-flash",
]

# 接口请求默认超时（推理模型较慢）
DEFAULT_TIMEOUT = 120.0


def _who(m: dict, self_label: str = "我", peer_label: str = "对方") -> str:
    """消息发送者名字：自己 → self_label；群聊用真实昵称；单聊用 peer_label。"""
    if m.get("is_self"):
        return self_label
    for k in ("sender", "sender_name", "display"):
        v = (m.get(k) or "").strip()
        if v:
            return v
    return peer_label


def _fmt_time(ts: int, with_year: bool = False) -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S" if with_year else "%m-%d %H:%M:%S",
                         time.localtime(ts))


def _fmt_media(t: int) -> str:
    """媒体类消息转成可读占位（原来直接丢弃，AI 看不到「谁在什么时候发了图」）。"""
    return {3: "[图片]", 34: "[语音]", 43: "[视频]", 47: "[表情包]",
            50: "[音视频通话]", 62: "[小视频]", 42: "[名片]", 48: "[位置]",
            49: "[链接/文件]", 51: "[状态消息]", 76: "[红包/转账]"}.get(t, "[非文字消息]")


def build_history(msgs: list[dict], max_msgs: int, self_label: str = "我",
                  peer_label: str = "对方", include_media: bool = True,
                  with_year: bool = False) -> list[dict]:
    """把消息列表转成 chat messages（每条都带【谁说的】+【完整时间】）。

    - 自己发的 role=assistant，标注 self_label；对方/群友 role=user，标注真实昵称。
    - 媒体类消息（图片/语音/表情等）转成占位，保留「谁 + 什么时候」信息。
    - max_msgs<=0 表示不限制（全量）。
    """
    out = []
    src_msgs = msgs if (max_msgs is None or max_msgs <= 0) else msgs[-max_msgs:]
    for m in src_msgs:
        t = int(m.get("type") or 0)
        text = (m.get("text") or "").strip()
        media_like = t in (3, 34, 43, 47, 50, 62, 42, 48, 49, 51, 76)
        if media_like:
            if not include_media:
                continue
            text = text if (t == 47 and text.startswith("[表情")) else _fmt_media(t)
        if not text:
            continue
        name = _who(m, self_label, peer_label)
        ts = m.get("ts") or 0
        role = "assistant" if m.get("is_self") else "user"
        out.append({
            "role": role,
            "content": f"[{_fmt_time(ts, with_year)}] {name}: {text}"
        })
    return out


def analyze_my_style(msgs: list[dict], max_msgs: int = 300) -> str:
    """从历史消息里分析「我」的说话风格（纯本地统计，不花 token）。

    返回一段风格描述：常用语气/口头禅/句长/表情使用。供 AI 出方案时模仿。
    """
    mine = [m.get("text", "") for m in msgs[-max_msgs:] if m.get("is_self") and m.get("text")]
    if not mine:
        return ""
    total = len(mine)
    # 常用词（去掉单字/语气词）
    from collections import Counter
    words = Counter()
    exclam = quest = emoji = 0
    avg_len = 0
    for t in mine:
        t = t.strip()
        avg_len += len(t)
        exclam += t.count("！") + t.count("!")
        quest += t.count("？") + t.count("?")
        # 简单提取 2+ 字词（按常见标点/空格切）
        for tok in re.split(r"[，。！？、\s,.!?]", t):
            if len(tok) >= 2 and not tok.isdigit():
                words[tok] += 1
        # 常见表情符号
        for e in ("😂", "😅", "😊", "🤣", "🙈", "😏", "😭", "👍", "❤", "🐶", "🙃", "🥰"):
            if e in t:
                emoji += 1
    avg_len = avg_len / max(1, total)
    top = [w for w, _ in words.most_common(8)]
    parts = []
    if top:
        parts.append(f"常用词/口头禅：{'、'.join(top)}")
    if avg_len:
        parts.append(f"单条消息平均 {avg_len:.0f} 字" + ("（偏简短，话不多）" if avg_len < 12 else "（中等长度）" if avg_len < 30 else "（比较能聊）"))
    style = []
    if exclam / max(1, total) > 0.15:
        style.append("爱用感叹号（语气热情/活泼）")
    if quest / max(1, total) > 0.1:
        style.append("常反问/提问（互动感强）")
    if emoji / max(1, total) > 0.2:
        style.append(f"爱用表情（如{'、'.join(list({'😂','😅','😊','🤣','🙈','😏','😭','👍','❤','🥰'})[:3])}等）")
    if not style:
        style.append("语气平稳，较少夸张")
    parts.append("、".join(style))
    return "；".join(parts)


class AISession:
    """一个聊天对象的 AI 会话：持有上下文历史，负责生成建议。"""

    def __init__(self, cfg: dict, talker: str, peer_name: str, self_name: str = "我"):
        self.cfg = cfg
        self.talker = talker
        self.peer_name = peer_name or "对方"
        self.self_name = self_name or "我"
        self.history: list[dict] = []   # 已送入的对话历史（assistant 是我们的回复）
        self._lock = threading.Lock()

    # ---- 上下文管理 ----

    def _system_prompt(self, memory: dict | None = None) -> str:
        """系统提示词：基础教练 prompt + 人格底色 + 长期记忆（越用越懂）。"""
        base = self.cfg.get("prompt", DEFAULT_CONFIG["prompt"])
        persona = (self.cfg.get("persona") or "").strip()
        if persona:
            base += (
                f"\n\n【我的人格底色】{persona}\n"
                "请严格按照这个人格底色来扮演我，我发出的每一句话（包括 A/B/C 方案里的候选）"
                "都要符合这个人格，不要说违背人格底色的话。"
            )
        # 长期记忆：之前对这个人/这段关系的记忆沉淀（重启后仍在）
        if memory:
            parts = []
            if memory.get("relation"):
                parts.append(f"我和她的关系：{memory['relation']}")
            if memory.get("key_info"):
                parts.append(f"我了解到的她的关键信息：{memory['key_info']}")
            if memory.get("style"):
                parts.append(f"我自己的说话风格（要模仿）：{memory['style']}")
            cons = memory.get("conclusions") or []
            if cons:
                parts.append(f"之前分析的结论（要延续）：{'；'.join(cons[-5:])}")
            if parts:
                base += "\n\n【长期记忆】\n" + "\n".join(parts) + "\n（这些是你长期记住的内容，出方案时保持一致、越用越懂这个人）"
        return base

    def _reset_with(self, msgs: list[dict], memory: dict | None = None) -> None:
        """首次：把全部历史打包成 user 消息，附上系统提示。

        按用户需求：第一次打开该联系人 = 开启 AI 会话窗口，把该聊天**全部历史**
        喂给 AI，让它先分析（后续每条新消息再增量出建议）。memory 为长期记忆。
        """
        hist = build_history(msgs, self.cfg.get("first_ctx_msgs", 500),
                            self_label=self.self_name, peer_label=self.peer_name,
                            include_media=True, with_year=True)
        with self._lock:
            self.history = [{"role": "system", "content": self._system_prompt(memory)}]
            if hist:
                joined = "\n".join(h["content"] for h in hist)
                extra_task = (self.cfg.get("analysis_task") or "").strip()
                content = (COACH_ANALYSIS_PROMPT + "\n\n"
                           "以下是我们聊天记录（格式：[时间] 谁: 内容，按时间先后，全量）：\n"
                           + joined +
                           ("\n\n另外，我特别想让你重点看：\n" + extra_task if extra_task else "")
                           + "\n\n请按上面提示词逐条分析这段聊天，分析完等我给你新消息，"
                             "再针对每条给出回复方案。")
                self.history.append({"role": "user", "content": content})
            else:
                self.history.append({"role": "user", "content": "开始对话。"})

    def _append_user(self, text: str) -> None:
        with self._lock:
            self.history.append({"role": "user", "content": text})
            # 滚动窗口：限制总条数（system + 最近 N 条）
            limit = self.cfg.get("max_context_msgs", 80) + 4
            if len(self.history) > limit:
                keep = self.history[:1] + self.history[-(limit - 1):]
                self.history = keep

    def _append_assistant(self, text: str) -> None:
        with self._lock:
            self.history.append({"role": "assistant", "content": text})

    def _trim_history(self, history: list[dict]) -> list[dict]:
        """裁剪历史：保留 system + 聊天记录注记 + 最近 N 条完整问答。

        关键点是不能把问答对从中间切断——只留 user 丢了问题、或只留
        assistant 丢了语境，都会让 AI 看起来「失忆」。所以从后往前按成对的
        (user, assistant) 收集，保证每轮都是完整的一问一答。

        head 靠 role 和 _intro 标记做结构化识别，不能按固定下标猜：
        restore_history 回填的历史不一定以 system 开头，按下标切会把
        一整轮问答误当成 head 冻住。
        """
        if not history:
            return history
        head: list[dict] = []
        i = 0
        if history[0].get("role") == "system":
            head.append(history[0])
            i = 1
        while i < len(history) and history[i].get("_intro"):
            head.append(history[i])
            i += 1
        tail = history[i:]
        if not tail:
            return head
        max_msgs = max(2, int(self.cfg.get("max_context_msgs", 80)))
        turns: list[dict] = []
        j = len(tail) - 1
        while j >= 0 and len(turns) < max_msgs:
            if tail[j].get("role") == "assistant":
                # 往前找提出这轮问题的 user；配不成对的孤儿回答直接丢掉
                k = j - 1
                while k >= 0 and tail[k].get("role") != "user":
                    k -= 1
                if k < 0:
                    break
                turns[0:0] = tail[k:j + 1]
                j = k - 1
            else:
                # 还没被回答的提问（通常是本轮问题），保留
                turns.insert(0, tail[j])
                j -= 1
        return head + turns

    def restore_history(self, messages: list[dict], extra_context: str = "") -> None:
        """把已保存的会话回填进 s.history，让切换会话/重启后 AI 仍有上下文。

        messages 是 ai_chats.json 里的 [{who, text}, ...]，
        me -> user，ai -> assistant。

        这里必须补上 system 提示：聊天记录注记在首次 chat() 时会被重建，
        而恢复出来的历史让 need_ctx 为 False，那条注记和人格提示都不会
        再进 history。少了 system，AI 重启后就退回成普通聊天机器人。
        """
        pairs: list[dict] = []
        pending: list[str] = []
        for m in messages or []:
            text = (m.get("text") or "").strip()
            if not text:
                continue
            who = m.get("who")
            if who == "me":
                if pending:
                    pairs.append({"role": "assistant", "content": "\n\n".join(pending)})
                    pending = []
                pairs.append({"role": "user",
                              "content": text + "\n\n（请基于恋爱教练的身份给出建议。）"})
            elif who == "ai":
                pending.append(text)
        if pending:
            pairs.append({"role": "assistant", "content": "\n\n".join(pending)})
        if not pairs:
            return
        with self._lock:
            # 已有的历史优先（正在进行的会话不能被覆盖）
            if self.history:
                return
            memory = None
            self.history = [{"role": "system", "content": self._system_prompt(memory)}]
            # 标记为注记，_trim_history 才会把它当 head 一直保留
            self.history.append({
                "role": "user",
                "_intro": True,
                "content": "以下是我们之前关于这段关系的对话记录，请接着上面的分析继续回答。",
            })
            self.history.extend(pairs)
            self._restored_extra_ctx = (extra_context or "").strip()

    # ---- 生成 ----

    def suggest(self, msgs: list[dict], force_rebuild: bool = False,
                timeout: float = 120.0, memory: dict | None = None,
                on_first_done=None) -> tuple[str, bool]:
        """生成「下一句」建议。

        force_rebuild=True 时用全部历史重建上下文（首次/换人）；否则沿用会话，只追加最新一条。
        memory: 长期记忆（首次注入 prompt）。返回 (text, is_first)。
        """
        is_first = False
        if force_rebuild or not self.history:
            self._reset_with(msgs, memory=memory)
            is_first = True
        else:
            # 增量：取最新一条（对方刚发的）追加进上下文
            latest = msgs[-1] if msgs else None
            if latest:
                text = (latest.get("text") or "").strip()
                if text and not latest.get("is_self"):
                    self._append_user(f"[{_fmt_time(latest.get('ts') or 0, True)}] "
                                      f"{_who(latest, self.self_name, self.peer_name)}：{text}")
            else:
                self._append_user("对方发来一条消息，我该回什么？")

        model = self.cfg.get("model") or DEFAULT_CONFIG["model"]
        payload = {"model": model, "messages": list(self.history),
                   "temperature": 1.0, "max_tokens": 8000}
        data = _chat_completion(self.cfg, payload, timeout=timeout)
        text, reason = _completion_text(data)
        # 推理模型：max_tokens 预算是「推理 + 输出」共用，可能被推理链吃光导致输出为空
        if not text.strip() and reason == "length":
            payload["max_tokens"] = 16000
            data = _chat_completion(self.cfg, payload, timeout=timeout)
            text, _ = _completion_text(data)
        elif _looks_truncated(text):
            text = _continue_text(self.cfg, payload, text, timeout=timeout)
        text = _clean_suggest(text)
        if text:
            self._append_assistant(text)
        if is_first and text and on_first_done:
            on_first_done(text)
        return text, is_first


def _clean_suggest(text: str, limit: int = 20000) -> str:
    """清洗建议输出：保留三方案格式，去掉多余空行/引号包装。

    注意：早期版本硬编码 [:1500] 会把 AI 的复盘报告从中间砍断（用户看到的就是
    回答总是停在半句），这里改成按行收尾并放宽上限，长报告不再被腰斩。
    """
    text = (text or "").strip()
    lines = [ln.rstrip() for ln in text.splitlines()]
    lines = [ln for ln in lines if ln.strip()]
    out = "\n".join(lines)
    if len(out) <= limit:
        return out
    # 超长时按行边界截断，尽量保留完整句子
    cut = out[:limit]
    nl = cut.rfind("\n")
    if nl > limit * 0.6:
        cut = cut[:nl]
    return cut.rstrip()


def friendly_error(e: Exception) -> str:
    """把异常转成对用户友好的中文提示。"""
    err = str(e)
    if isinstance(e, urllib.error.HTTPError):
        body = ""
        try:
            body = e.read().decode("utf-8", "replace")[:200]
        except Exception:
            pass
        if e.code == 401:
            return "API 密钥无效，请检查 ⚙ AI 配置"
        if e.code == 404:
            return "接口地址或模型名不存在（404），请检查 API 地址和模型名"
        if e.code == 429:
            return "请求过于频繁（429），请稍后再试"
        if e.code >= 500:
            return f"模型服务暂时不可用（HTTP {e.code}），请稍后重试"
        return f"接口返回错误 HTTP {e.code}：{body or err}"
    if isinstance(e, urllib.error.URLError):
        reason = getattr(e, "reason", err)
        return f"网络连接失败：{reason}"
    if "timeout" in err.lower():
        return "请求超时，模型响应较慢，请稍后重试或换更快的模型"
    if "401" in err or "invalid" in err.lower() or "unauthorized" in err.lower():
        return "API 密钥无效，请检查 ⚙ AI 配置"
    if "json" in err.lower() or "expect" in err.lower():
        return f"接口返回格式异常：{err[:120]}"
    return err[:200]


def _chat_completion(cfg: dict, payload: dict, timeout: float = 120.0,
                     retries: int = 2) -> dict:
    """发一次 chat/completions 请求，网络抖动自动重试，返回完整 JSON。

    重试条件：连接被断（RemoteDisconnected）、URL 错误、5xx、超时。4xx（参数/鉴权）不重试。
    """
    url = cfg.get("api_url") or DEFAULT_CONFIG["api_url"]
    key = cfg.get("api_key") or ""
    last_err = None
    for attempt in range(retries + 1):
        if attempt:
            time.sleep(1.0 * attempt)  # 退避 1s, 2s
        req = urllib.request.Request(url, method="POST",
                                     data=json.dumps(payload).encode("utf-8"))
        req.add_header("Content-Type", "application/json")
        if key:
            req.add_header("Authorization", f"Bearer {key}")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code >= 500 or e.code == 429:
                last_err = e
                continue
            raise RuntimeError(friendly_error(e))
        except Exception as e:
            last_err = e
            if getattr(e, "code", None) == 401:
                raise RuntimeError("API 密钥无效，请检查 ⚙ AI 配置")
            continue
    raise RuntimeError(friendly_error(last_err))


def _chat_completion_stream(cfg: dict, payload: dict, on_delta, timeout: float = 120.0) -> str:
    """流式请求 chat/completions（SSE），逐段回调 on_delta(delta_text)，返回完整文本。

    兼容标准 OpenAI /chat/completions 的 stream=true：
      data: {"choices":[{"delta":{"content":"..."}}]}  ...  data: [DONE]
    非流式或不支持时自动回退到普通请求（on_delta 只收到最终整段）。
    """
    url = cfg.get("api_url") or DEFAULT_CONFIG["api_url"]
    key = cfg.get("api_key") or ""
    p = dict(payload)
    p["stream"] = True
    req = urllib.request.Request(url, method="POST",
                                 data=json.dumps(p).encode("utf-8"))
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "text/event-stream")
    if key:
        req.add_header("Authorization", f"Bearer {key}")

    parts: list[str] = []
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            for raw in resp:
                line = raw.decode("utf-8", "replace").strip()
                if not line or not line.startswith("data:"):
                    continue
                data_str = line[5:].strip()
                if data_str == "[DONE]":
                    break
                try:
                    obj = json.loads(data_str)
                except Exception:
                    continue
                ch = (obj.get("choices") or [{}])[0]
                delta = (ch.get("delta") or {}).get("content")
                if not delta:
                    delta = (ch.get("message") or {}).get("content")
                if delta:
                    parts.append(delta)
                    try:
                        on_delta(delta)
                    except Exception:
                        pass
    except urllib.error.HTTPError as e:
        # 服务端不支持流式（400/404 等）→ 回退非流式
        if e.code in (400, 404, 405, 422, 501):
            data = _chat_completion(cfg, payload, timeout=timeout)
            text, _ = _completion_text(data)
            if text:
                try:
                    on_delta(text)
                except Exception:
                    pass
            return text.strip()
        raise RuntimeError(friendly_error(e))
    except Exception as e:
        if parts:                      # 已经流了一半：保留已收到的内容
            return "".join(parts).strip()
        raise RuntimeError(friendly_error(e))
    return "".join(parts).strip()


def _completion_text(data: dict) -> tuple[str, str]:
    """从 chat/completions JSON 里取正文 + finish_reason。"""
    choice = (data.get("choices") or [{}])[0]
    return (choice.get("message") or {}).get("content") or "", choice.get("finish_reason") or ""


def _looks_truncated(text: str) -> bool:
    """Detect replies cut off mid-sentence (common with reasoning models).

    Signs: ends without sentence punctuation, ends on comma/colon, ends on an
    unclosed markdown marker, or ends on a dangling table separator.
    """
    t = (text or "").rstrip()
    if not t:
        return False
    # unmatched ** bold marker -> model was interrupted mid-emphasis
    if t.count("**") % 2 == 1:
        return True
    if t.count("```") % 2 == 1:
        return True
    # dangling markdown table separator row (header printed, body missing)
    lines = [ln.strip() for ln in t.splitlines() if ln.strip()]
    if lines:
        last = lines[-1]
        if last.startswith("|") and set(last) <= set("|-: "):
            return True
        if last.count("|") == 1 and last.startswith("|"):
            return True
    t2 = t.rstrip("*_`#>-").rstrip()
    if not t2:
        return True
    if t2[-1] in "\u3002\uff01\uff1f!?\u2026\uff5e~\uff09)\u300d\u300f\u3011\"\u201d\u2019":
        return False
    if t2[-1] in "\uff0c,\u3001\uff1b;\uff1a:":
        return True
    if len(t2) > 40 and t2[-1] not in "\u3002\uff01\uff1f!?\u201d\u2019":
        return True
    return False


def _continue_text(cfg: dict, payload: dict, so_far: str, on_delta=None,
                   rounds: int = 3, timeout: float = 120.0) -> str:
    """??????????????????????????????

    ???? rounds ??on_delta ? None ??????????????????
    """
    extra = so_far
    for _ in range(rounds):
        if not _looks_truncated(extra):
            break
        cont_payload = dict(payload)
        cont_payload["messages"] = list(payload.get("messages") or []) + [
            {"role": "assistant", "content": extra},
            {"role": "user", "content":
             "\u4f60\u4e0a\u9762\u7684\u56de\u7b54\u88ab\u622a\u65ad\u4e86\uff0c\u8bf7\u4ece\u88ab\u622a\u65ad\u5904"
             "\u7ee7\u7eed\u63a5\u7740\u5199\u5b8c\uff0c\u4e0d\u8981\u91cd\u590d\u5df2\u7ecf\u5199\u8fc7\u7684\u5185\u5bb9\uff0c"
             "\u4e0d\u8981\u91cd\u65b0\u5f00\u5934\uff0c\u4fdd\u6301\u540c\u6837\u7684\u683c\u5f0f\u548c\u8bed\u6c14\u3002"},
        ]
        cont_payload["max_tokens"] = max(int(payload.get("max_tokens") or 2000), 2000)
        cont_payload.pop("stream", None)
        try:
            data = _chat_completion(cfg, cont_payload, timeout=timeout)
        except Exception:
            break
        piece, _reason = _completion_text(data)
        piece = (piece or "").strip()
        if not piece:
            break
        if on_delta is not None:
            try:
                on_delta(piece)
            except Exception:
                pass
        extra = extra + piece
    return extra


def test_connection(cfg: dict, timeout: float = 60.0) -> dict:
    """测试 API 连接：发一条最小请求，返回 {ok, elapsed, msg, content}。

    不修改任何配置、不写任何文件；供设置面板「一键测试」按钮调用。
    """
    url = cfg.get("api_url") or DEFAULT_CONFIG["api_url"]
    key = cfg.get("api_key") or ""
    model = cfg.get("model") or DEFAULT_CONFIG["model"]
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "请回复：连接成功"}],
        "temperature": 0.2,
        "max_tokens": 30,
    }
    t0 = time.time()
    try:
        data = _chat_completion(cfg, payload, timeout=timeout)
        content = ((data.get("choices") or [{}])[0].get("message", {}).get("content") or "").strip()
        elapsed = time.time() - t0
        return {"ok": True, "elapsed": elapsed, "msg": f"连接成功（{elapsed:.1f}s）",
                "content": content or ""}
    except Exception as e:
        return {"ok": False, "elapsed": time.time() - t0, "msg": friendly_error(e),
                "content": ""}


REVIEW_PROMPT = (
    "你是资深的聊天教练、恋爱咨询师，帮我复盘我跟异性的这一段微信聊天，学到撩妹/聊天的技巧。\n"
    "请用中文输出以下结构：\n"
    "【对方状态】对方目前对你的兴趣/情绪/态度如何？给出1-2句判断，并说明依据（她说了什么、语气如何）。\n"
    "【我做得好的】我这段聊天里有哪些亮点（幽默、共情、展示了价值等），1-3条。\n"
    "【我踩的坑/可改进】我哪里说尬了、哪里显得太急/太舔/太无聊，怎么改更好，1-3条。\n"
    "【兴趣信号】对方有没有释放好感信号（主动找话题、分享生活、表情包、关心你等），列出来。\n"
    "【下一步建议】接下来怎么推进（该升温、该约出来、还是该放一放），具体到下一句怎么回，给1-2个方向的示例话术。\n"
    "语气要客观、具体、可操作，不要泛泛而谈，要能真正教我怎么聊。"
)


def build_review_messages(msgs: list[dict], max_msgs: int = 200, prompt: str = None) -> list[dict]:
    """复盘用的消息列表：只保留文本类，尽量多给（比建议窗口大）。"""
    hist = build_history(msgs, max_msgs, self_label="我")
    sys_msg = {"role": "system", "content": prompt or REVIEW_PROMPT}
    if not hist:
        return [sys_msg, {"role": "user", "content": "（这段聊天没有可分析的文字消息）"}]
    joined = "\n".join(h["content"] for h in hist)
    return [sys_msg, {"role": "user", "content": f"以下是聊天记录：\n{joined}"}]


class AIClient:
    """全局 AI 客户端：持有各聊天对象的会话，配置持久化到 data/ai_config.json。"""

    def __init__(self, data_dir: str):
        self.cfg_path = os.path.join(data_dir, "ai_config.json")
        self.data_dir = data_dir
        self.cfg = self._load()
        self.sessions: dict[str, AISession] = {}
        self.memory_store = None   # buddy_memory 模块（由客户端注入）
        self.account = ""          # 当前账号
        self._lock = threading.Lock()

    def _load(self) -> dict:
        try:
            with open(self.cfg_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            c = dict(DEFAULT_CONFIG)
            # prompt 不持久化：跟随代码最新版（避免旧提示词覆盖新能力）
            if "prompt" in data:
                data.pop("prompt", None)
            c.update({k: v for k, v in data.items() if k in DEFAULT_CONFIG})
            return c
        except Exception:
            return dict(DEFAULT_CONFIG)

    def save(self) -> None:
        to_save = {k: v for k, v in self.cfg.items() if k != "prompt"}
        with open(self.cfg_path, "w", encoding="utf-8") as f:
            json.dump(to_save, f, ensure_ascii=False, indent=2)

    def update_config(self, **kw) -> dict:
        for k, v in kw.items():
            if k in DEFAULT_CONFIG and k != "prompt":
                self.cfg[k] = v
        self.save()
        return self.cfg

    def session_for(self, talker: str, peer_name: str, self_name: str = "我") -> AISession:
        with self._lock:
            s = self.sessions.get(talker)
            if s is None:
                s = AISession(self.cfg, talker, peer_name, self_name)
                self.sessions[talker] = s
            else:
                # 昵称/备注可能会后补或变更，缓存的会话要跟着更新，
                # 否则新建的会话仍会用旧的 peer_name 渲染聊天记录注记
                if peer_name:
                    s.peer_name = peer_name
                if self_name:
                    s.self_name = self_name
            return s

    def reset_session(self, talker: str) -> None:
        with self._lock:
            self.sessions.pop(talker, None)

    # ---- 供界面调用的便捷方法 ----

    def enabled(self) -> bool:
        return bool(self.cfg.get("enabled") and self.cfg.get("api_key"))

    def suggest(self, talker: str, msgs: list[dict], peer_name: str,
                self_name: str = "我", force_rebuild: bool = False,
                timeout: float = 120.0) -> str | None:
        """生成建议，带长期记忆：首次读记忆注入，分析完沉淀记忆（越用越懂）。"""
        s = self.session_for(talker, peer_name, self_name)
        # 首次建立会话：读长期记忆注入
        memory = None
        if self.memory_store is not None:
            memory = self.memory_store.get(self.account, talker)
            # 首次且没有风格画像时，自动分析我的说话风格并沉淀
            if (force_rebuild or not s.history) and not (memory or {}).get("style"):
                style = analyze_my_style(msgs)
                if style:
                    self.memory_store.update(self.account, talker, style=style)

        def on_first_done(analysis: str):
            # 首次分析完成：把分析结论沉淀进记忆（简洁起见存前几条要点）
            if self.memory_store is not None and analysis:
                # 提取分析里的关键句（按常见标记切分）
                import re as _re
                lines = [ln.strip() for ln in analysis.splitlines()
                         if ln.strip() and len(ln.strip()) > 6]
                cons = lines[:5]
                if cons:
                    self.memory_store.update(self.account, talker,
                                             conclusion="；".join(cons)[:300])

        text, _first = s.suggest(msgs, force_rebuild=force_rebuild,
                                 timeout=timeout, memory=memory,
                                 on_first_done=on_first_done)
        return text

    def review(self, talker: str, msgs: list[dict], timeout: float = 120.0,
               extra_context: str = "", self_name: str = "我") -> str | None:
        """一次性 AI 复盘（恋爱教练视角）：全量聊天（带谁+时间）+ 补充场景。

        返回结构化教练报告。extra_context：用户补充的、不在聊天里的场景/背景。
        """
        if not self.enabled():
            raise RuntimeError("AI 未配置")
        s = self.session_for(talker, self.cfg.get("peer_label", "对方"), self_name)
        memory = None
        if self.memory_store is not None:
            memory = self.memory_store.get(self.account, talker)
        sys_prompt = _chat_system_prompt(self.cfg, memory, persona=self.cfg.get("persona", ""))
        style = (memory or {}).get("style") or analyze_my_style(msgs)
        if style:
            sys_prompt += f"\n\n【我的说话风格（复盘建议要模仿我的口吻）】{style}"
        ctx, has_msgs = build_chat_context_limited(msgs, s.peer_name, extra_context,
                                                   self_name, max_chars=90000)
        if has_msgs:
            extra_task = (self.cfg.get("analysis_task") or "").strip()
            user = (COACH_ANALYSIS_PROMPT + "\n\n"
                    "以下是这段聊天的完整记录（含谁说的、几点发的）和我的补充场景：\n\n"
                    + ctx +
                    ("\n\n另外，我特别想让你重点看：\n" + extra_task if extra_task else "")
                    + "\n\n请按上面提示词逐条给出完整复盘。")
        else:
            user = "（当前没有可分析的聊天记录）"
        payload = {"model": self.cfg.get("model", DEFAULT_CONFIG["model"]),
                   "messages": [{"role": "system", "content": sys_prompt},
                                {"role": "user", "content": user}],
                   "temperature": 0.7, "max_tokens": 8000}
        try:
            data = _chat_completion(self.cfg, payload, timeout=timeout)
        except Exception:
            # 全量超出上下文：回退最近 800 条再试一次
            ctx2, _ok = build_chat_context(msgs, s.peer_name, extra_context,
                                           self_name, max_msgs=800)
            payload["messages"] = [{"role": "system", "content": sys_prompt},
                                   {"role": "user", "content": ctx2 + "\n\n请输出完整复盘。"}]
            data = _chat_completion(self.cfg, payload, timeout=timeout)
        text, reason = _completion_text(data)
        if not text.strip() and reason == "length":
            payload["max_tokens"] = 16000
            data = _chat_completion(self.cfg, payload, timeout=timeout)
            text, _ = _completion_text(data)
        elif _looks_truncated(text):
            text = _continue_text(self.cfg, payload, text, timeout=timeout)
        return text.strip()

    def chat(self, talker: str, msgs: list[dict], peer_name: str, user_msg: str,
             self_name: str = "我", force_context: bool = True,
             timeout: float = 120.0, extra_context: str = "",
             on_delta=None, stream: bool = True) -> str:
        """自由对话：AI 作为聊天高手/恋爱教练，基于全量聊天 + 补充场景回答。

        上下文管理（参考豆包/ChatGPT 的做法）：
          - 聊天记录（谁说的 + 几点发的）只在会话首次注入一次，作为一条 user 消息；
          - 之后每轮提问只追加「我的问题」和「AI 回答」，走滚动窗口；
          - 这样既省 token，又能让 AI 记住多轮追问，且不会反复重发全量记录。
        on_delta: 流式增量回调（逐段文本），用于界面打字机效果。
        """
        s = self.session_for(talker, peer_name, self_name)
        with s._lock:
            need_ctx = force_context or not s.history
            if need_ctx:
                s.history = []
                # 首次（或强制重建）：注入聊天记录 + 补充场景 + 长期记忆
                memory = None
                style = ""
                if self.memory_store is not None:
                    memory = self.memory_store.get(self.account, talker)
                    style = (memory or {}).get("style") or analyze_my_style(msgs)
                sys_prompt = _chat_system_prompt(self.cfg, memory, persona=self.cfg.get("persona", ""))
                if style:
                    sys_prompt += f"\n\n【我的说话风格（你出建议时要模仿我的口吻）】{style}"
                ctx, has_msgs = build_chat_context_limited(msgs, peer_name, extra_context,
                                                           self_name, max_chars=90000)
                s.history = [{"role": "system", "content": sys_prompt}]
                extra_task = (self.cfg.get("analysis_task") or "").strip()
                intro = (ctx + "\n\n以上是这次分析的聊天记录（含谁说的、几点发的）"
                         "和我的补充场景。\n\n"
                         + ("另外，我特别想让你重点看：\n" + extra_task + "\n\n" if extra_task else "")
                         + "接下来我会向你提问，请始终基于这些记录，"
                           "以恋爱教练/聊天高手的身份回答。"
                         if has_msgs else
                         "（当前没有聊天记录。我会在下面补充背景，之后请基于背景分析。）")
                s.history.append({"role": "user", "_intro": True, "content": intro})
                # 用户补充的场景（不在聊天记录里的情况）每一轮都要带上
                # 否则只有第一轮看得到，追问时 AI 就当没这回事
                eff_extra = ((extra_context or "").strip()
                             or getattr(s, "_extra_ctx", "").strip()
                             or getattr(s, "_restored_extra_ctx", "").strip())
                if eff_extra and not has_msgs:
                    s.history.append({"role": "user",
                                     "content": "补充场景\n" + eff_extra})
                # 记录下来，供本会话后续轮次引用
                s._extra_ctx = eff_extra

        # 本轮问题
        with s._lock:
            s.history.append({"role": "user",
                              "content": user_msg + "\n\n（请以恋爱教练/聊天高手的身份回答。）"})
            # 滚动窗口：system + 聊天记录注入 + 最近 N 轮
            payload_msgs = s._trim_history(s.history)

        payload = {
            "model": self.cfg.get("model", DEFAULT_CONFIG["model"]),
            "messages": payload_msgs,
            "temperature": 0.8,
            "max_tokens": 8000,
        }
        text = ""
        if stream and on_delta is not None:
            try:
                text = _chat_completion_stream(self.cfg, payload, on_delta, timeout=timeout)
            except RuntimeError:
                data = _chat_completion(self.cfg, payload, timeout=timeout)
                text, _ = _completion_text(data)
                if text:
                    try:
                        on_delta(text)
                    except Exception:
                        pass
        else:
            data = _chat_completion(self.cfg, payload, timeout=timeout)
            text, reason = _completion_text(data)
            if not text.strip() and reason == "length":
                payload["max_tokens"] = 16000
                data = _chat_completion(self.cfg, payload, timeout=timeout)
                text, _ = _completion_text(data)
        if _looks_truncated(text):
            text = _continue_text(self.cfg, payload, text, on_delta, timeout=timeout)
        text = text.strip()
        if text:
            with s._lock:
                s.history.append({"role": "assistant", "content": text})
        return text

    def reset(self, talker: str) -> None:
        self.reset_session(talker)


COACH_ANALYSIS_PROMPT = (
    '1.回复时长、主动发起聊天是谁、是否单向输出（只有你找对方）、是否经常已读不回 / 敷衍短句（嗯、哦、哈哈）\n'
    '2.双方说话篇幅，是轮流分享，还是一方一直在倾诉，另一方只被动应答\n'
    '3.吵架是愿意解释沟通，还是冷暴力、回避问题、翻旧账、人身攻击、甩锅\n'
    '4.话题层次：只聊暧昧撩骚，还是愿意聊未来、家庭、规划、内心想法\n'
    '5.行动力匹配：嘴上承诺很多，但聊天从不落地（只画饼，不提见面、安排）\n'
    '6.不要只看有没有秒回，看**内容浓度**，高兴趣：带情绪、细节、反问，会延伸话题，主动说自己的事，用表情包 / 调侃，低兴趣：简短、封闭式回答（嗯，还好，还行），不反问，不延展，转移话题，你分析的时候要列出这些：哪些话题她积极、哪些她冷淡，**记住她感兴趣的方向，避开无感话题**\n'
    '7.用户有没有过度暴露需求感\n'
    '8.节奏与拉扯：有没有收放，还是一味猛攻\n'
    '9.话题层级：是浅层闲聊，还是情绪共鸣\n'
    '\n'
    '10.**不要逐字抠，不要纠结某一句说错**，看整体趋势：她对你的兴趣是上升还是下降。一句话不会直接毁掉，持续模式才会，聊天只是铺垫，**最终目标是落地邀约**。复盘看：有没有自然把话题往见面引导，还是一直线上无限拉扯\n'
    '11.根据女生的聊天总结女生的性格特点，将女生进行分类，## 五级目标划分：\n'
    '\n'
    '- **S 女（女玩家）**\n'
    '  本身懂情感套路，洞察力强，很难被拿捏，属于同段位对手，一般会避开。\n'
    '\n'
    '- **A 级（女玩家 / 开放型）**\n'
    '  社交丰富，不排斥暧昧。**匹配浪子人设**，用悲情故事、破碎感吸引，主打短期关系。\n'
    '\n'
    '- **B 级（寂寞女）**\n'
    '  内心孤单、缺陪伴，情感空虚。浪子人设最容易勾起她的情绪共鸣，很容易心疼对方。\n'
    '\n'
    '- **C 级（乖乖女）**\n'
    '  单纯、传统、共情强，有拯救者情结，最容易中招。**匹配帝王人设**，塑造稳重强大、有故事感的形象，让她产生崇拜感。\n'
    '\n'
    '- **D 级（保守 / 烈女）**\n'
    '  边界感强，思想传统，最难攻破，需要帝王 + 诗人结合慢慢渗透，周期很长。\n'
    '\n'
    '12.另外还有 4 类按性格划分（实操筛选）:\n'
    '\n'
    '- **拯救者型（圣母情结）**：看见对方脆弱、受伤就心疼，总想治愈、拯救他，是五步陷阱最喜欢的目标，专门用探索陷阱卖惨，激发保护欲。\n'
    '- **缺爱型**：从小缺少关心，一点点温柔就沦陷，很容易把线上情绪当成真爱。\n'
    '- **讨好型**：习惯反思自己，吵架优先自我检讨，后面自尊摧毁陷阱专门拿捏这类人。\n'
    '- **浪漫幻想型**：向往灵魂伴侣，容易被诗人人设的文艺、悲情故事打动。\n'
    '\n'
    '13.选择出配套的 3 种男生人设（用来对应不同类型女生）\n'
    '\n'
    '- **浪子**：受过情伤、不相信爱情，适合 A、B 类女生\n'
    '- **帝王**：成熟强大、背负压力，适合 C、D 乖乖女\n'
    '- **诗人**：敏感文艺、内心孤独，属于通杀款，各类女生都能用\n'
    '\n'
    '- 这一点如果你觉得聊天记录太少，不足以判断出来要给用户说明\n'
    '\n'
    '根据以上内容来分析下面聊天记录，最后你再给出行动路线，接下来需要怎么做。\n'
    '\n'
)

CHAT_COACH_PROMPT = (
    "你是一个顶级的微信聊天高手、恋爱教练（约会教练/沟通教练）。你的唯一身份是教练，"
    "绝对不是我的普通朋友，也不要站在朋友立场附和、安慰、打哈哈。\n"
    "你的职责：基于我提供的聊天记录（每条都带谁说的、几点发的），帮我看透对方的心理、"
    "判断关系阶段、指出我说得好的地方和踩的坑，并给出可执行、具体到下一句话的推进建议。\n"
    "要求：\n"
    "1. 分析要具体，引用聊天里的原话和时间点作为依据，不要泛泛而谈；\n"
    "2. 判断要直给：对方到底对我有没有意思、现在处于什么阶段（暧昧/普通朋友/降温），敢下结论；\n"
    "3. 给的建议要能直接照抄发出（口语化、不过度抠字眼），并讲清为什么；\n"
    "4. 全程站在教练视角，帮我把关系往好的方向推进，不教我当舔狗，也不教我冷暴力。"
)


def _chat_system_prompt(cfg: dict, memory: dict | None, persona: str = "") -> str:
    """自由对话/复盘用的系统提示：教练人设（默认）+ 人格底色 + 长期记忆。"""
    parts = [CHAT_COACH_PROMPT]
    persona = (persona or "").strip()
    if persona:
        parts.append(f"【我的人格底色（用户自己设定，必须遵守）】{persona}")
    if memory:
        m_lines = []
        if memory.get("relation"):
            m_lines.append(f"我和她的关系：{memory['relation']}")
        if memory.get("key_info"):
            m_lines.append(f"我了解到的她的关键信息：{memory['key_info']}")
        if memory.get("style"):
            m_lines.append(f"我自己的说话风格（要模仿）：{memory['style']}")
        cons = memory.get("conclusions") or []
        if cons:
            m_lines.append(f"之前分析的结论（要延续）：{chr(10).join(cons[-5:])}")
        if m_lines:
            parts.append("【长期记忆（越用越懂，分析时保持一致）】\n" + "\n".join(m_lines))
    return "\n\n".join(parts)


def build_chat_context_limited(msgs: list[dict], peer_name: str = "对方",
                               extra_context: str = "", self_name: str = "我",
                               max_chars: int = 90000) -> tuple[str, bool]:
    """拼装 AI 上下文：全量优先，超 max_chars 自动回退最近 N 条。

    最近的消息最相关，所以超预算时从最近的消息往回取。
    """
    ctx, ok = build_chat_context(msgs, peer_name, extra_context, self_name, max_msgs=0)
    if ok and len(ctx) <= max_chars:
        return ctx, ok
    for n in (3000, 2000, 1200, 800, 500, 300, 200, 120, 80, 50):
        ctx2, ok2 = build_chat_context(msgs, peer_name, extra_context, self_name, max_msgs=n)
        if ok2 and len(ctx2) <= max_chars:
            return ctx2, ok2
    return build_chat_context(msgs, peer_name, extra_context, self_name, max_msgs=50)


def build_chat_context(msgs: list[dict], peer_name: str = "对方",
                       extra_context: str = "", self_name: str = "我",
                       max_msgs: int = 0) -> tuple[str, bool]:
    """拼装给 AI 的聊天记录文本（全量，每条带【谁 + 几点几发】，媒体保留占位）。

    返回 (context_text, has_msgs)。extra_context 为聊天记录之外、用户补充的场景/背景。
    """
    hist = build_history(msgs, max_msgs, self_label=self_name, peer_label=peer_name,
                         include_media=True, with_year=True)
    parts = []
    if hist:
        parts.append("以下是聊天记录（格式：每条=[时间] 谁: 内容，按时间先后）：\n"
                     + "\n".join(h["content"] for h in hist))
    if extra_context and extra_context.strip():
        parts.append("以下是我补充的、不在聊天记录里的重要背景/场景（分析时要一起考虑）：\n"
                     + extra_context.strip())
    if not parts:
        return "", False
    return "\n\n".join(parts), True
