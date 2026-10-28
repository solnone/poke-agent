toolsList = [
    {
        "type": "function",
        "function": {
            "name": "choose_move",
            "description": "Selects and executes an available attacking or status move.",
            "parameters": {
                "type": "object",
                "properties": {
                    "move_name": {
                        "type": "string",
                        "description": "The move ID exactly as shown in the available moves list (e.g., 'thunderbolt', 'swordsdance'). Must be one of the available moves.",
                    },
                },
                "required": ["move_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "choose_switch",
            "description": "Selects an available Pokémon from the bench to switch into.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pokemon_name": {
                        "type": "string",
                        "description": "The species name exactly as shown in the available switches list (e.g., 'Pikachu', 'Charizard'). Must be one of the available switches.",
                    },
                },
                "required": ["pokemon_name"],
            },
        },
    },
]