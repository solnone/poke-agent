# agent.py
import os
import json
import asyncio
import logging
from openai import AsyncOpenAI  # Use AsyncOpenAI for async compatibility with poke-env

# Import necessary poke-env components for type hinting and functionality
from poke_env.player import Player
try:
    from poke_env.battle import Battle, Move, Pokemon
except ImportError:
    from poke_env.environment.battle import Battle
    from poke_env.environment.move import Move
    from poke_env.environment.pokemon import Pokemon
from poke_agent.tools import toolsList
from poke_agent import config

class OpenAIAgent(Player):
    """
    An AI agent for Pokemon Showdown that uses OpenAI's API
    with function calling to decide its moves.
    Configured via .env file or environment variables.
    """
    def __init__(self, *args, model: str | None = None, api_key: str | None = None, base_url: str | None = None, **kwargs):
        # Pass account_configuration and other Player args/kwargs to the parent
        super().__init__(*args, **kwargs)

        # Initialize OpenAI client
        # Retrieve key and base_url from parameter, config (.env), or environment variable
        api_key = api_key or config.OPENAI_API_KEY or os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY is not set in .env or environment variables.")

        resolved_base_url = base_url or config.OPENAI_BASE_URL or os.environ.get("OPENAI_BASE_URL")
        if isinstance(resolved_base_url, str):
            resolved_base_url = resolved_base_url.strip() or None

        # Use AsyncOpenAI for compatibility with poke-env's async nature
        client_kwargs = {"api_key": api_key, "max_retries": 3}
        if resolved_base_url:
            client_kwargs["base_url"] = resolved_base_url
        self.openai_client = AsyncOpenAI(**client_kwargs)
        self.model = model or config.OPENAI_MODEL or os.environ.get("OPENAI_MODEL", "gpt-6-luna")

        # Define the tools OpenAI can call
        self.tools = toolsList

    def _format_battle_state(self, battle: Battle) -> str:
        """Formats the current battle state into a string for the LLM."""
        # Own active Pokemon details
        active_pkmn = battle.active_pokemon
        active_pkmn_info = f"Your active Pokemon: {active_pkmn.species} " \
                           f"(Type: {'/'.join(map(str, active_pkmn.types))}) " \
                           f"HP: {active_pkmn.current_hp_fraction * 100:.1f}% " \
                           f"Status: {active_pkmn.status.name if active_pkmn.status else 'None'} " \
                           f"Boosts: {active_pkmn.boosts}"

        # Opponent active Pokemon details
        opponent_pkmn = battle.opponent_active_pokemon
        opponent_pkmn_info = f"Opponent's active Pokemon: {opponent_pkmn.species} " \
                             f"(Type: {'/'.join(map(str, opponent_pkmn.types))}) " \
                             f"HP: {opponent_pkmn.current_hp_fraction * 100:.1f}% " \
                             f"Status: {opponent_pkmn.status.name if opponent_pkmn.status else 'None'} " \
                             f"Boosts: {opponent_pkmn.boosts}"

        # Available moves
        available_moves_info = "Available moves:\n"
        if battle.available_moves:
            for move in battle.available_moves:
                available_moves_info += f"- {move.id} (Type: {move.type}, BP: {move.base_power}, Acc: {move.accuracy}, PP: {move.current_pp}/{move.max_pp}, Cat: {move.category.name})\n"
        else:
            available_moves_info += "- None (Must switch or Struggle)\n"

        # Available switches
        available_switches_info = "Available switches:\n"
        if battle.available_switches:
            for pkmn in battle.available_switches:
                available_switches_info += f"- {pkmn.species} (HP: {pkmn.current_hp_fraction * 100:.1f}%, Status: {pkmn.status.name if pkmn.status else 'None'})\n"
        else:
            available_switches_info += "- None\n"

        # Combine information
        state_str = f"{active_pkmn_info}\n" \
                    f"{opponent_pkmn_info}\n\n" \
                    f"{available_moves_info}\n" \
                    f"{available_switches_info}\n" \
                    f"Weather: {battle.weather}\n" \
                    f"Terrains: {battle.fields}\n" \
                    f"Your Side Conditions: {battle.side_conditions}\n" \
                    f"Opponent Side Conditions: {battle.opponent_side_conditions}\n"

        return state_str.strip()

    async def _get_openai_decision(self, battle_state: str) -> dict | None:
        """Sends state to OpenAI and gets back the tool call decision."""
        system_prompt = (
            "You are a skilled Pokemon battle AI. Your goal is to win the battle. "
            "Based on the current battle state, decide the best action: either use an available move or switch to an available Pokémon. "
            "Consider type matchups, HP, status conditions, field effects, entry hazards, and potential opponent actions. "
            "Only choose actions listed as available."
        )
        user_prompt = f"Current Battle State:\n{battle_state}\n\nChoose the best action by calling the appropriate tool ('choose_move' or 'choose_switch')."

        try:
            response = await self.openai_client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                tools=self.tools,
                tool_choice="required", # Force a tool call every turn
                temperature=0.5, # Adjust for creativity vs consistency
            )
            message = response.choices[0].message
            if message.tool_calls:
                tool_call = message.tool_calls[0]
                function_name = tool_call.function.name
                try:
                    arguments = json.loads(tool_call.function.arguments)
                    return {"name": function_name, "arguments": arguments}
                except json.JSONDecodeError:
                    logging.error(f"Error decoding tool call arguments: {tool_call.function.arguments}")
                    return None
            else:
                # Model decided not to call a tool (or generated text instead)
                logging.warning(f"OpenAI did not return a tool call. Response: {message.content}")
                return None

        except Exception as e:
            logging.error(f"Error during OpenAI API call: {e}")
            return None

    def _find_move_by_name(self, battle: Battle, move_name: str) -> Move | None:
        """Finds the Move object corresponding to the given name."""
        normalized = move_name.lower().replace(" ", "").replace("-", "")
        for move in battle.available_moves:
            if move.id == normalized or move.id == move_name.lower():
                return move
            if hasattr(move, 'name') and move.name.lower() == move_name.lower():
                return move
        return None

    def _find_pokemon_by_name(self, battle: Battle, pokemon_name: str) -> Pokemon | None:
        """Finds the Pokemon object corresponding to the given species name."""
        # Normalize name for comparison
        normalized_name = pokemon_name.lower()
        for pkmn in battle.available_switches:
            if pkmn.species.lower() == normalized_name:
                return pkmn
        return None

    async def choose_move(self, battle: Battle) -> str:
        """
        Main decision-making function called by poke-env each turn.
        """
        # 1. Format battle state
        battle_state_str = self._format_battle_state(battle)
        # print(f"\n--- Turn {battle.turn} ---") # Debugging
        # print(battle_state_str) # Debugging

        # 2. Get decision from OpenAI
        decision = await self._get_openai_decision(battle_state_str)

        # 3. Parse decision and create order
        if decision:
            function_name = decision["name"]
            args = decision["arguments"]
            # print(f"OpenAI Recommended: {function_name} with args {args}") # Debugging

            if function_name == "choose_move":
                move_name = args.get("move_name")
                if move_name:
                    chosen_move = self._find_move_by_name(battle, move_name)
                    if chosen_move and chosen_move in battle.available_moves:
                        # print(f"Action: Using move {chosen_move.id}")
                        return self.create_order(chosen_move)
                    else:
                        logging.warning(f"OpenAI chose unavailable/invalid move '{move_name}'. Falling back.")
                else:
                    logging.warning(f"OpenAI 'choose_move' called without 'move_name'. Falling back.")

            elif function_name == "choose_switch":
                pokemon_name = args.get("pokemon_name")
                if pokemon_name:
                    chosen_switch = self._find_pokemon_by_name(battle, pokemon_name)
                    if chosen_switch and chosen_switch in battle.available_switches:
                        # print(f"Action: Switching to {chosen_switch.species}")
                        return self.create_order(chosen_switch)
                    else:
                        logging.warning(f"OpenAI chose unavailable/invalid switch '{pokemon_name}'. Falling back.")
                else:
                    logging.warning(f"OpenAI 'choose_switch' called without 'pokemon_name'. Falling back.")

        # 4. Fallback if API fails, returns invalid action, or no function call
        logging.warning("Fallback: Choosing random move/switch.")
        # Ensure options exist before choosing randomly
        available_options = battle.available_moves + battle.available_switches
        if available_options:
            # Use the built-in random choice method from Player for fallback
            return self.choose_random_move(battle)
        else:
            # Should only happen if forced to Struggle
            return self.choose_default_move(battle)