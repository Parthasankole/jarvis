import json
import requests
from rich.console import Console
from pydantic import BaseModel
import jarvis_tools as tools
import jarvis_profile as profile
import jarvis_router as router

console = Console()


def get_system_prompt() -> str:
    user_name = profile.get_user_name()
    return f"""You are JARVIS, a sophisticated, loyal, and intelligent AI companion running locally on Windows.
Your creator and user is {user_name}. Always address him warmly and respectfully as {user_name}.
When you want to use a tool, output ONLY valid JSON in ONE of these formats:
{{"type":"see_screen","args":{{"prompt":"what is on the screen?"}}}}
{{"type":"click_mouse","args":{{"button":"left","clicks":1}}}}
{{"type":"move_cursor","args":{{"x":"center"}}}}
{{"type":"scroll_mouse","args":{{"direction":"down","amount":3}}}}
{{"type":"type_text","args":{{"text":"hello"}}}}
{{"type":"press_key","args":{{"key_name":"enter"}}}}
{{"type":"press_hotkey","args":{{"combo":"ctrl+c"}}}}
{{"type":"open_onscreen_keyboard","args":{{}}}}
{{"type":"close_onscreen_keyboard","args":{{}}}}
{{"type":"open_installed_app","args":{{"name":"Brave"}}}}
{{"type":"close_app","args":{{"name":"Brave"}}}}
{{"type":"close_current_tab","args":{{}}}}
{{"type":"close_current_window","args":{{}}}}
{{"type":"search_installed_apps","args":{{"query":"photo"}}}}
{{"type":"refresh_app_index","args":{{}}}}
{{"type":"system_status","args":{{}}}}
{{"type":"get_time_date","args":{{}}}}
{{"type":"get_weather","args":{{"city":""}}}}
{{"type":"media_control","args":{{"action":"play"}}}}
{{"type":"set_volume","args":{{"action":"up"}}}}
{{"type":"take_screenshot","args":{{}}}}
{{"type":"get_active_window","args":{{}}}}
{{"type":"list_open_windows","args":{{}}}}
{{"type":"get_clipboard","args":{{}}}}
{{"type":"set_clipboard","args":{{"text":"..."}}}}
{{"type":"open_web","args":{{"query":"youtube..."}}}}
{{"type":"save_memory","args":{{"key":"...","value":"..."}}}}
{{"type":"recall_memory","args":{{"query":"..."}}}}
{{"type":"create_file","args":{{"relative_path":"notes.txt","content":"hello"}}}}
{{"type":"youtube_play","args":{{"query":"song name"}}}}
{{"type":"web_search","args":{{"query":"search query"}}}}
{{"type":"final","text":"your normal response"}}

Rules:
- Output ONLY the JSON object. No extra markdown or conversational text before or after the JSON.
- Prefer open_installed_app for opening apps by name. Keep responses concise.
"""


class Call(BaseModel):
    type: str
    name: str | None = None
    args: dict | None = None
    text: str | None = None


def extract_json(text: str):
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("No JSON")
    return json.loads(text[start:end + 1])


def ollama_chat(messages, model: str = None, num_predict: int = 150):
    return router.chat_routed(
        messages=messages,
        model=model,
        format="json",
        num_predict=num_predict,
        timeout=120
    )


def run_tool(tool_type: str, args: dict) -> str:
    args = args or {}
    if tool_type == "see_screen": return tools.see_screen(args.get("prompt", ""))
    if tool_type == "get_cursor_position": return tools.get_cursor_position()
    if tool_type == "move_cursor": return tools.move_cursor(args.get("x", "center"), args.get("y"))
    if tool_type == "move_cursor_relative": return tools.move_cursor_relative(args.get("dx", 0), args.get("dy", 0))
    if tool_type == "click_mouse": return tools.click_mouse(args.get("button", "left"), args.get("clicks", 1), args.get("x"), args.get("y"))
    if tool_type == "scroll_mouse": return tools.scroll_mouse(args.get("direction", "down"), args.get("amount", 3))
    if tool_type == "type_text": return tools.type_text(args.get("text", ""))
    if tool_type == "press_key": return tools.press_key(args.get("key_name", ""))
    if tool_type == "press_hotkey": return tools.press_hotkey(args.get("combo", ""))
    if tool_type == "open_onscreen_keyboard": return tools.open_onscreen_keyboard()
    if tool_type == "close_onscreen_keyboard": return tools.close_onscreen_keyboard()
    if tool_type == "open_installed_app": return tools.open_installed_app(args.get("name", ""))
    if tool_type == "open_app": return tools.open_app(args.get("app_key", ""))
    if tool_type == "close_app": return tools.close_app(args.get("name", ""))
    if tool_type == "close_current_tab": return tools.close_current_tab()
    if tool_type == "close_current_window": return tools.close_current_window()
    if tool_type == "search_installed_apps": return tools.search_installed_apps(args.get("query", ""))
    if tool_type == "refresh_app_index": return tools.refresh_app_index()
    if tool_type == "system_status": return tools.system_status()
    if tool_type == "get_time_date": return tools.get_time_date()
    if tool_type == "get_weather": return tools.get_weather(args.get("city", ""))
    if tool_type == "media_control": return tools.media_control(args.get("action", ""))
    if tool_type == "set_volume": return tools.set_volume(args.get("action", ""))
    if tool_type == "take_screenshot": return tools.take_screenshot()
    if tool_type == "get_active_window": return tools.get_active_window()
    if tool_type == "list_open_windows": return tools.list_open_windows()
    if tool_type == "get_clipboard": return tools.get_clipboard()
    if tool_type == "set_clipboard": return tools.set_clipboard(args.get("text", ""))
    if tool_type == "open_web": return tools.open_web(args.get("query", ""))
    if tool_type == "save_memory": return tools.save_memory(args.get("key", ""), args.get("value", ""))
    if tool_type == "recall_memory": return tools.recall_memory(args.get("query", ""))
    if tool_type == "create_file": return tools.create_file(args.get("relative_path", ""), args.get("content", ""))
    if tool_type == "youtube_play": return tools.youtube_play(args.get("query", ""))
    if tool_type == "web_search": return tools.web_search(args.get("query", ""))
    return f"Unknown tool: {tool_type}"


def main():
    user_name = profile.get_user_name()
    console.print(f"[bold green]JARVIS Terminal System Online for {user_name}.[/bold green] Type [bold]exit[/bold] to quit.")
    messages = [{"role": "system", "content": get_system_prompt()}]

    while True:
        user = console.input(f"\n[bold cyan]{user_name}:[/bold cyan] ").strip()
        if user.lower() in ("exit", "quit"):
            break
        if user.lower() in ("clear", "cls"):
            console.clear()
            continue
        if not user:
            continue

        chosen_model, role = router.route_request(user)
        console.print(f"[dim]Routing to '{chosen_model}' ({role})...[/dim]")

        token_budget = 200 if role == "reasoning" else 120
        messages.append({"role": "user", "content": user})
        raw = ollama_chat(messages, model=chosen_model, num_predict=token_budget)

        try:
            call = Call(**extract_json(raw))
        except Exception:
            console.print(f"[bold yellow]Jarvis:[/bold yellow] {raw}")
            messages.append({"role": "assistant", "content": raw})
            continue

        if call.type == "final":
            console.print(f"[bold yellow]Jarvis:[/bold yellow] {call.text}")
            messages.append({"role": "assistant", "content": raw})
            continue

        tool_to_run = call.name if call.type == "tool" else call.type
        args = call.args or {}

        result = run_tool(tool_to_run, args)
        console.print(f"[bold magenta]Tool [{tool_to_run}]:[/bold magenta] {result}")

        # Ask model for clean conversational reply
        messages.append({"role": "assistant", "content": raw})
        messages.append({"role": "user", "content": f"Tool result: {result}. Reply ONLY with: {{\"type\":\"final\",\"text\":\"...\"}}"})
        final_raw = ollama_chat(messages)

        try:
            final_call = Call(**extract_json(final_raw))
            if final_call.type == "final":
                console.print(f"[bold yellow]Jarvis:[/bold yellow] {final_call.text}")
            else:
                console.print(f"[bold yellow]Jarvis:[/bold yellow] {final_raw}")
        except Exception:
            console.print(f"[bold yellow]Jarvis:[/bold yellow] {final_raw}")

        messages.append({"role": "assistant", "content": final_raw})


if __name__ == "__main__":
    main()