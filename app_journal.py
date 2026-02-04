#!/usr/bin/env python
"""Streamlit web app for the JournalAgent."""

import streamlit as st
import importlib.util
from dotenv import load_dotenv

load_dotenv()

# Direct import to bypass agents/__init__.py
spec = importlib.util.spec_from_file_location("agent_journal", "agents/agent_journal.py")
agent_journal = importlib.util.module_from_spec(spec)
spec.loader.exec_module(agent_journal)
JournalAgent = agent_journal.JournalAgent
MODELS = agent_journal.MODELS

# Page config
st.set_page_config(page_title="日記小幫手", page_icon="📔", layout="centered")
st.title("📔 日記小幫手")

# Sidebar for settings
with st.sidebar:
    st.header("設定")
    model = st.selectbox("模型", ["sonnet", "opus"], index=0)

    st.divider()
    st.header("書寫階段")

    # Phase indicator
    if "phase" in st.session_state:
        phase_labels = {
            "cbt": "📖 CBT日記",
            "narrative": "📖 敘事探索",
            "finalize": "✨ 完成日記",
        }
        st.info(f"目前階段：{phase_labels.get(st.session_state.phase, st.session_state.phase)}")

    if st.button("🔄 開始新日記"):
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.rerun()

# Initialize session state
if "agent" not in st.session_state:
    st.session_state.agent = JournalAgent(model=model)
    st.session_state.messages = []
    st.session_state.phase = "cbt"
    st.session_state.messages.append({"role": "assistant", "content": "嗨！今天想聊什麼呢？"})

agent = st.session_state.agent

# Helper to check if agent suggested transition
def agent_suggested(keyword):
    if st.session_state.messages:
        last_msg = st.session_state.messages[-1]
        if last_msg["role"] == "assistant":
            content = last_msg["content"].lower()
            # Check both English and Chinese keywords
            keyword_map = {
                "summarize": ["summarize", "整理日記"],
                "reframe": ["reframe", "重塑日記"],
            }
            keywords = keyword_map.get(keyword.lower(), [keyword.lower()])
            return any(k in content for k in keywords)
    return False

# Display chat messages
for message in st.session_state.messages:
    avatar = "🐱" if message["role"] == "assistant" else None
    with st.chat_message(message["role"], avatar=avatar):
        st.markdown(message["content"])

# Command buttons based on phase - only show when agent suggests
col1, col2, col3 = st.columns(3)

if st.session_state.phase == "cbt":
    # Count CBT turns (5 turns = 11 messages: system + 5*(user + assistant))
    cbt_turns = (len(getattr(agent, 'messages', [])) - 1) // 2
    # Show "Journaling prompts" button at the start
    if not agent.init_journal:
        with col1:
            if st.button("💡給我靈感"):
                with st.spinner("問句產生中..."):
                    prompts = agent.generate_prompts()
                st.session_state.messages.append({"role": "assistant", "content": prompts})
                st.rerun()
    # Show Summarize button after 5 turns or when agent suggests summarize
    elif (agent_suggested("summarize") or cbt_turns >= 5) and not agent.reframed_journal:
        with col1:
            if st.button("整理日記"):
                with st.spinner("整理中..."):
                    response = agent.reframe()
                st.session_state.messages.append({"role": "assistant", "content": response})
                st.rerun()
        with col2:
            if st.button("繼續聊聊", key="cbt_explore"):
                with st.spinner("思考中..."):
                    agent.cbt_receive("我想要繼續聊聊")
                    response = agent.cbt_reply()
                st.session_state.messages.append({"role": "user", "content": "我想要繼續聊聊"})
                st.session_state.messages.append({"role": "assistant", "content": response})
                st.rerun()
    # Show Next Step button after reframe is done
    elif agent.reframed_journal:
        with col1:
            if st.button("進入敘事探索"):
                agent._save_to_archive(agent.reframed_journal, "reframe")
                with st.spinner("開始敘事探索..."):
                    response = agent.start_narrative()
                st.session_state.messages.append({"role": "assistant", "content": response})
                st.session_state.phase = "narrative"
                st.rerun()
        with col2:
            if st.button("繼續聊聊", key="cbt_explore_after_reframe"):
                with st.spinner("思考中..."):
                    agent.cbt_receive("我想要繼續聊聊")
                    response = agent.cbt_reply()
                st.session_state.messages.append({"role": "user", "content": "我想要繼續聊聊"})
                st.session_state.messages.append({"role": "assistant", "content": response})
                # Reset reframed_journal so we stay in exploration
                agent.reframed_journal = None
                st.rerun()

elif st.session_state.phase == "narrative":
    # Count narrative turns (5 turns = 13 messages: system + user kickoff + assistant + 5*(user + assistant))
    narrative_turns = (len(getattr(agent, 'narrative_messages', [])) - 3) // 2
    # Show Reframe button after 5 turns or when agent suggests reframe
    if (agent_suggested("reframe") or narrative_turns >= 5) and not agent.final_summary:
        with col1:
            if st.button("重塑日記"):
                with st.spinner("重塑中..."):
                    response = agent.summarize()
                st.session_state.messages.append({"role": "assistant", "content": response})
                st.rerun()
        with col2:
            if st.button("繼續聊聊", key="narrative_explore"):
                with st.spinner("思考中..."):
                    agent.narrative_receive("我想要繼續聊聊")
                    response = agent.narrative_reply()
                st.session_state.messages.append({"role": "user", "content": "我想要繼續聊聊"})
                st.session_state.messages.append({"role": "assistant", "content": response})
                st.rerun()
    # Show Finalize button after summarize is done
    elif agent.final_summary:
        with col1:
            if st.button("完成日記"):
                agent._save_to_archive(agent.final_summary, "summarize")
                st.session_state.phase = "finalize"
                st.rerun()
        with col2:
            if st.button("繼續聊聊", key="narrative_explore_after_summary"):
                with st.spinner("思考中..."):
                    agent.narrative_receive("我想要繼續聊聊")
                    response = agent.narrative_reply()
                st.session_state.messages.append({"role": "user", "content": "我想要繼續聊聊"})
                st.session_state.messages.append({"role": "assistant", "content": response})
                # Reset final_summary so we stay in exploration
                agent.final_summary = None
                st.rerun()

elif st.session_state.phase == "finalize":
    # Show title input if not yet submitted
    if not hasattr(agent, 'journal_title') or not agent.journal_title:
        st.info("請給這篇的日記取一個標題")
        title = st.text_input("日記標題", key="journal_title_input", placeholder="輸入你的故事標題...")
        if st.button("送出"):
            if title:
                with st.spinner("完成中..."):
                    response = agent.finalize(title)
                st.session_state.messages.append({"role": "assistant", "content": response})
                st.rerun()
            else:
                st.warning("請先輸入標題")
    # Show end button after feedback is complete
    elif agent.feedback_complete:
        st.divider()
        st.subheader("📝 心得回饋")
        user_feedback = st.text_area(
            "請分享你對這次書寫體驗的心得或建議：",
            key="user_feedback_input",
            placeholder="這次的書寫體驗如何？有什麼想法或建議嗎？",
            height=100
        )

        # Initialize feedback submitted state
        if "feedback_submitted" not in st.session_state:
            st.session_state.feedback_submitted = False

        fcol1, fcol2 = st.columns(2)
        with fcol1:
            if st.button("送出回饋"):
                if user_feedback:
                    with st.spinner("儲存回饋中..."):
                        success = agent.save_feedback(user_feedback)
                    if success:
                        st.session_state.feedback_submitted = True
                        st.success("回饋已儲存至 Google Sheets！")
                    else:
                        st.error("回饋儲存失敗，請檢查 Google Sheets 設定。")
                else:
                    st.warning("請先輸入回饋內容")

        with fcol2:
            if st.button("結束日記書寫"):
                st.success(f"日記「{agent.journal_title}」已完成！")
                st.balloons()

# Chat input
if prompt := st.chat_input("輸入訊息..."):
    # Add user message
    st.session_state.messages.append({"role": "user", "content": prompt})

    with st.chat_message("user"):
        st.markdown(prompt)

    # Generate response based on phase
    with st.chat_message("assistant", avatar="🐱"):
        with st.spinner("思考中..."):
            if st.session_state.phase == "cbt":
                agent.cbt_receive(prompt)
                response = agent.cbt_reply()
            elif st.session_state.phase == "narrative":
                agent.narrative_receive(prompt)
                response = agent.narrative_reply()
            elif st.session_state.phase == "finalize":
                agent.finalize_receive(prompt)
                response = agent.finalize_reply()
            else:
                response = "未知階段"

        st.markdown(response)

    st.session_state.messages.append({"role": "assistant", "content": response})
    st.rerun()