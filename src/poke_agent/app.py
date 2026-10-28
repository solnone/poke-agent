# app.py
import asyncio
import logging
import os
import random
import threading
import traceback

import gradio as gr
import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse
from poke_env import AccountConfiguration, LocalhostServerConfiguration
from poke_env.player import Player, RandomPlayer

from poke_agent import config
from poke_agent.agents import OpenAIAgent

# --- Configuration ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(threadName)s - %(levelname)s - %(message)s",
)

SERVER_CONFIG = LocalhostServerConfiguration
RANDOM_PLAYER_BASE_NAME = "RandAgent"
OPENAI_AGENT_BASE_NAME = "OpenAIAgent"
DEFAULT_BATTLE_FORMAT = "gen9randombattle"


def clean_agent_type(agent_type: str) -> str:
    """Extract standard agent type from dropdown label."""
    if "OpenAI" in agent_type:
        return "OpenAI Agent"
    if "Random" in agent_type:
        return "Random Player"
    return agent_type


# --- Agent Creation (Async - Required by poke-env) ---
async def create_agent_async(agent_type: str, battle_format: str = DEFAULT_BATTLE_FORMAT, prefix: str = "") -> Player | str:
    """
    Creates and initializes a SINGLE agent instance with a unique username.
    This function MUST be async because Player initialization involves async network setup.
    Returns the Player object on success, or an error string on failure.
    """
    cleaned_type = clean_agent_type(agent_type)
    logging.info(f"Attempting to create agent of type: {cleaned_type} (prefix: {prefix})")
    username = "unknown_agent"
    agent_suffix = random.randint(100, 9999)
    prefix_clean = prefix.strip() if prefix else ""

    try:
        if cleaned_type == "Random Player":
            username = f"{prefix_clean}Rand{agent_suffix}" if prefix_clean else f"{RANDOM_PLAYER_BASE_NAME}{agent_suffix}"
            account_config = AccountConfiguration(username, None)
            logging.info(f"Initializing RandomPlayer with username: {username} on local server")
            player = RandomPlayer(
                account_configuration=account_config,
                server_configuration=SERVER_CONFIG,
                battle_format=battle_format,
                start_listening=True,
            )
        elif cleaned_type == "OpenAI Agent":
            api_key = config.OPENAI_API_KEY or os.getenv("OPENAI_API_KEY")
            if not api_key:
                error_message = "Error: Cannot create OpenAI Agent. OPENAI_API_KEY is missing in .env or environment variables."
                logging.error(error_message)
                return error_message
            username = f"{prefix_clean}OpenAI{agent_suffix}" if prefix_clean else f"{OPENAI_AGENT_BASE_NAME}{agent_suffix}"
            account_config = AccountConfiguration(username, None)
            logging.info(f"Initializing OpenAIAgent with username: {username} on local server")
            player = OpenAIAgent(
                account_configuration=account_config,
                server_configuration=SERVER_CONFIG,
                battle_format=battle_format,
                start_listening=True,
            )
        else:
            error_message = f"Error: Invalid agent type '{agent_type}' requested."
            logging.error(error_message)
            return error_message

        logging.info(f"Agent object ({username}) created successfully.")
        return player

    except Exception as e:
        msg = f"Error creating agent {username}: {e}"
        logging.error(msg)
        logging.error(traceback.format_exc())
        return msg


# --- Battle Invitation (Async - Required by poke-env) ---
async def send_battle_invite_async(player: Player, opponent_username: str, battle_format: str) -> str:
    """
    Sends a challenge using the provided player object.
    This function MUST be async as sending challenges involves network I/O.
    Returns a status string (success or error message).
    """
    if not isinstance(player, Player):
        err_msg = f"Internal Error: Invalid object passed instead of Player: {type(player)}"
        logging.error(err_msg)
        raise TypeError(err_msg)

    player_username = getattr(player, 'username', 'unknown_agent')

    try:
        logging.info(f"Attempting to send challenge from {player_username} to {opponent_username} in format {battle_format}")
        await player.send_challenges(opponent_username, n_challenges=1)
        success_msg = f"Battle invitation ({battle_format}) sent to '{opponent_username}' from bot '{player_username}'."
        logging.info(success_msg)
        return success_msg

    except Exception as e:
        logging.error(f"Error sending challenge from {player_username} to {opponent_username}: {e}")
        logging.error(traceback.format_exc())
        raise


# --- Background Task Runners ---
def run_agent_vs_agent_in_background(p1_type: str, p2_type: str, battle_format: str):
    """
    Runs a battle between two agents in a separate background thread.
    """
    thread_name = threading.current_thread().name
    logging.info(f"[{thread_name}] Background thread started for Agent vs Agent: {p1_type} vs {p2_type}")

    async def _run():
        p1_res = await create_agent_async(p1_type, battle_format, prefix="P1")
        p2_res = await create_agent_async(p2_type, battle_format, prefix="P2")

        if isinstance(p1_res, str):
            logging.error(f"[{thread_name}] P1 creation failed: {p1_res}")
            return
        if isinstance(p2_res, str):
            logging.error(f"[{thread_name}] P2 creation failed: {p2_res}")
            return

        agent1: Player = p1_res
        agent2: Player = p2_res

        logging.info(f"[{thread_name}] Starting battle: {agent1.username} vs {agent2.username}")
        battle_task = asyncio.create_task(agent1.battle_against(agent2, n_battles=1))

        # Check for battle room ID
        for _ in range(50):
            if agent1.battles:
                room_id = list(agent1.battles.keys())[0]
                logging.info(f"[{thread_name}] 🎮 Active Battle Room: {room_id}")
                break
            await asyncio.sleep(0.1)
        else:
            logging.warning(f"[{thread_name}] Could not detect battle room ID within timeout.")

        await battle_task
        logging.info(
            f"[{thread_name}] Battle ended! {agent1.username} ({agent1.n_won_battles} wins) vs "
            f"{agent2.username} ({agent2.n_won_battles} wins)"
        )

    try:
        asyncio.run(_run())
        logging.info(f"[{thread_name}] Agent vs Agent thread finished successfully.")
    except Exception as e:
        logging.error(f"[{thread_name}] Error in agent vs agent battle: {e}")
        logging.error(traceback.format_exc())


def run_agent_vs_human_in_background(agent_type: str, target_username: str, battle_format: str, prefix: str = "Bot"):
    """
    Creates an agent and sends a challenge to a human player.
    """
    thread_name = threading.current_thread().name
    logging.info(f"[{thread_name}] Background thread started for {agent_type} vs human {target_username}.")

    async def _run():
        agent_or_error = await create_agent_async(agent_type, battle_format, prefix=prefix)
        if isinstance(agent_or_error, str):
            logging.error(f"[{thread_name}] Agent creation failed: {agent_or_error}")
            return

        player_instance: Player = agent_or_error
        player_username = getattr(player_instance, 'username', 'agent')
        logging.info(f"[{thread_name}] Agent {player_username} created, proceeding to challenge {target_username}.")

        try:
            result = await send_battle_invite_async(player_instance, target_username, battle_format)
            logging.info(f"[{thread_name}] Challenge result: {result}")
        except Exception as invite_error:
            logging.error(f"[{thread_name}] Failed to send challenge: {invite_error}")

    try:
        asyncio.run(_run())
        logging.info(f"[{thread_name}] Finished challenge to {target_username}.")
    except Exception as e:
        logging.error(f"[{thread_name}] Error in agent vs human challenge: {e}")
        logging.error(traceback.format_exc())


# --- Gradio Dispatch Logic ---
def start_battle_dispatch(p1_type: str, p1_name: str, p2_type: str, p2_name: str) -> str:
    """
    Validates inputs, decides battle mode, starts background tasks, and returns status.
    """
    p1_is_human = "Human" in p1_type
    p2_is_human = "Human" in p2_type
    p1_name_clean = p1_name.strip()
    p2_name_clean = p2_name.strip()

    if p1_is_human and not p1_name_clean:
        return "⚠️ **請輸入 Player 1 的 Showdown 使用者名稱！**"
    if p2_is_human and not p2_name_clean:
        return "⚠️ **請輸入 Player 2 的 Showdown 使用者名稱！**"

    # Case 1: Human vs Human
    if p1_is_human and p2_is_human:
        return (
            f"ℹ️ **雙方皆為真人玩家**：`{p1_name_clean}` vs `{p2_name_clean}`\n\n"
            "請在下方 Showdown 或各自開啟瀏覽器視窗登入暱稱，"
            f"並在 Showdown 搜尋對方或在聊天室輸入 `/challenge {p2_name_clean}` 即可直接對戰！"
        )

    # Case 2: Agent vs Agent
    if not p1_is_human and not p2_is_human:
        thread = threading.Thread(
            target=run_agent_vs_agent_in_background,
            args=(p1_type, p2_type, DEFAULT_BATTLE_FORMAT),
            daemon=True
        )
        thread.start()
        return (
            f"🚀 **AI vs AI 對戰已在背景啟動！**\n\n"
            f"* **Player 1 (紅方)**: {p1_type}\n"
            f"* **Player 2 (藍方)**: {p2_type}\n\n"
            "👀 **如何觀戰？**\n"
            "請在下方 Showdown 介面點擊 **「Watch a battle」** 即可看到進行中的對戰並進入即時觀戰！"
        )

    # Case 3 & 4: One agent vs one human (either side)
    agent_type = p1_type if not p1_is_human else p2_type
    human_name = p2_name_clean if not p1_is_human else p1_name_clean
    prefix = "P1" if not p1_is_human else "P2"

    thread = threading.Thread(
        target=run_agent_vs_human_in_background,
        args=(agent_type, human_name, DEFAULT_BATTLE_FORMAT, prefix),
        daemon=True,
    )
    thread.start()
    return (
        f"📨 **對戰邀請發送中！**\n\n"
        f"Bot ({agent_type}) 正向真人玩家 **`{human_name}`** 發送挑戰。\n"
        f"請在下方 Showdown 介面確認已使用該暱稱登入，並點擊 **Accept** 接受對戰！"
    )


# --- Gradio UI Definition ---
def main_app():
    """Creates and returns the Gradio application interface."""

    agent_options = [
        "🤖 OpenAI Agent",
        "🎲 Random Player",
        "👤 Human Player (真人玩家)"
    ]

    with gr.Blocks(title="Pokemon Showdown Multi-Challenger (Local)") as demo:
        gr.Markdown("# 🎮 Pokémon Battle Arena (Local Server)")
        gr.Markdown(
            "支援 **AI vs AI 觀戰**、**人機對戰** 與 **雙人自由配對**！\n\n"
            "💡 *提示：你也可以隨時在獨立瀏覽器分頁使用：[http://localhost.psim.us/](http://localhost.psim.us/)*"
        )

        with gr.Row():
            with gr.Column(scale=1):
                gr.Markdown("### 🔴 Player 1 (紅方)")
                p1_type = gr.Dropdown(
                    label="Player 1 角色類型",
                    choices=agent_options,
                    value="🤖 OpenAI Agent",
                )
                p1_name = gr.Textbox(
                    label="Player 1 Showdown 暱稱",
                    placeholder="若選真人請輸入暱稱，AI 則自動產生",
                    value="",
                    visible=False,
                )

            with gr.Column(scale=1):
                gr.Markdown("### 🔵 Player 2 (藍方)")
                p2_type = gr.Dropdown(
                    label="Player 2 角色類型",
                    choices=agent_options,
                    value="🎲 Random Player",
                )
                p2_name = gr.Textbox(
                    label="Player 2 Showdown 暱稱",
                    placeholder="若選真人請輸入暱稱，AI 則自動產生",
                    value="",
                    visible=False,
                )

        # 動態顯示/隱藏真人暱稱輸入框
        def toggle_human_input(choice):
            return gr.update(visible=("Human" in choice))

        p1_type.change(fn=toggle_human_input, inputs=p1_type, outputs=p1_name)
        p2_type.change(fn=toggle_human_input, inputs=p2_type, outputs=p2_name)

        with gr.Row():
            battle_button = gr.Button("⚔️ 開始對戰 / 發起挑戰", variant="primary", scale=1)

        status_box = gr.Markdown(
            value="📌 *尚未發起對戰。請設定上方 Player 1 與 Player 2 後點擊「開始對戰 / 發起挑戰」！*"
        )

        gr.HTML("""
        <iframe
            src="/showdown-client"
            width="100%" height="800" style="border: none;" referrerpolicy="no-referrer">
        </iframe>
        """)

        battle_button.click(
            fn=start_battle_dispatch,
            inputs=[p1_type, p1_name, p2_type, p2_name],
            outputs=status_box,
        )

    return demo

# --- Application Entry Point ---
def main() -> None:
    demo = main_app()
    server_app = FastAPI()

    @server_app.get("/showdown-client")
    def get_showdown_client():
        html_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "showdown_client.html")
        return FileResponse(html_path)

    app = gr.mount_gradio_app(server_app, demo, path="/")
    logging.info("Starting Gradio Pokemon Agent at http://127.0.0.1:7860 ...")
    uvicorn.run(app, host="127.0.0.1", port=7860)


if __name__ == "__main__":
    main()