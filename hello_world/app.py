import os
import json
import base64
import requests
import boto3
from nacl.signing import VerifyKey
from nacl.exceptions import BadSignatureError
import urllib.request
from urllib.error import URLError

# Discord bot configuration
PUBLIC_KEY = os.environ.get('DISCORD_PUBLIC_KEY')
BOT_TOKEN = os.environ.get('BOT_TOKEN')
APPLICATION_ID = os.environ.get('APPLICATION_ID')
DYNAMODB_TABLE_NAME = os.environ.get('DYNAMODB_TABLE_NAME')
api_key = os.environ.get('API_KEY')

# Initialize DynamoDB client
dynamodb = boto3.resource('dynamodb')
users_table = dynamodb.Table(DYNAMODB_TABLE_NAME)

def handle_command(body_json, interaction_id, interaction_token):
    try:
        command = body_json.get('data', {}).get('name')
        if command == 'balance':
            return balance_command(body_json, interaction_id, interaction_token)
        elif command == 'shop':
            return shop_command(body_json, interaction_id, interaction_token)
        elif command == 'buy':
            return buy_command(body_json, interaction_id, interaction_token)
        elif command == 'submit_image':
            return submit_image_command(body_json, interaction_id, interaction_token, api_key)
        else:
            print(f"Unknown command: {command}")
            return error_response(400, 'Unknown command')
    except KeyError as e:
        print(f"KeyError in handle_command: {e}")
        return error_response(400, 'Invalid request payload')
    except Exception as e:
        print(f"Unexpected error in handle_command: {e}")
        return error_response(500, 'Internal server error')

def error_response(status_code, message):
    return {
        'statusCode': status_code,
        'body': json.dumps({'error': message}),
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*',
        }
    }

def successful_response(body):
    return {
        'statusCode': 200,
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*',
        },
        'body': json.dumps(body)
    }

def lambda_handler(event, context):
    try:
        headers = event.get('headers', {})
        signature = headers.get("x-signature-ed25519")
        timestamp = headers.get("x-signature-timestamp")

        # Log headers for debugging
        print(f"Received headers: {headers}")

        if not signature or not timestamp:
            raise ValueError('Missing signature or timestamp')

        body = event.get('body', '')
        if event.get('isBase64Encoded', False):
            body = base64.b64decode(body).decode('utf-8')

        print(f"Received event: {json.dumps(event)}")
        print("Body: ", body)

        try:
            body_json = json.loads(body)
        except json.JSONDecodeError:
            print("Invalid JSON in body")
            return error_response(400, 'Invalid JSON')

        verify_key = VerifyKey(bytes.fromhex(PUBLIC_KEY))
        try:
            verify_key.verify(f'{timestamp}{body}'.encode(), bytes.fromhex(signature))
        except BadSignatureError:
            print("Invalid request signature")
            return error_response(401, 'Invalid request signature')

        # Handle PING request
        if body_json.get('type') == 1:
            return successful_response({"type": 1})

        interaction_id = body_json.get('id')
        interaction_token = body_json.get('token')

        return handle_command(body_json, interaction_id, interaction_token)

    except ValueError as e:
        print(f"ValueError: {e}")
        return error_response(400, str(e))
    except Exception as e:
        print(f"Unexpected error: {e}")
        return error_response(500, 'Internal server error')

def balance_command(body_json, interaction_id, interaction_token):
    try:
        user_id = body_json['member']['user']['id']
        tokens = get_user_tokens(user_id)
        return send_interaction_response(interaction_id, interaction_token, {
            'type': 4,
            'data': {
                'content': f"<@{user_id}>, you have {tokens} tokens."
            }
        })
    except KeyError as e:
        print(f"KeyError in balance_command: {e}")
        return error_response(400, 'Invalid user information')

def shop_command(body_json, interaction_id, interaction_token):
    try:
        shop_items = {
            "item1": 10,
            "item2": 20,
            "item3": 30
        }
        shop_list = "\n".join([f"{item}: {price} tokens" for item, price in shop_items.items()])
        return send_interaction_response(interaction_id, interaction_token, {
            'type': 4,
            'data': {
                'content': f"**Shop Items:**\n{shop_list}"
            }
        })
    except Exception as e:
        print(f"Error in shop_command: {e}")
        return error_response(500, 'Internal server error')

def buy_command(body_json, interaction_id, interaction_token):
    try:
        user_id = body_json['member']['user']['id']
        item = body_json['data']['options'][0]['value']
        shop_items = {
            "item1": 10,
            "item2": 20,
            "item3": 30
        }
        if item in shop_items:
            price = shop_items[item]
            current_tokens = get_user_tokens(user_id)
            if current_tokens >= price:
                update_user_tokens(user_id, -price)
                message = f"<@{user_id}>, you bought {item} for {price} tokens!"
                send_dm_with_embed(user_id, item, price)
            else:
                message = f"<@{user_id}>, you don't have enough tokens to buy {item}!"
        else:
            message = f"<@{user_id}>, the item {item} does not exist in the shop."
        return send_interaction_response(interaction_id, interaction_token, {
            'type': 4,
            'data': {
                'content': message
            }
        })
    except KeyError as e:
        print(f"KeyError in buy_command: {e}")
        return error_response(400, 'Invalid item')

def get_user_tokens(user_id):
    try:
        response = users_table.get_item(Key={'user_id': user_id})
        if 'Item' in response:
            return response['Item'].get('tokens', 0)
        return 0
    except Exception as e:
        print(f"Error getting user tokens: {e}")
        return 0

def update_user_tokens(user_id, amount):
    try:
        users_table.update_item(
            Key={'user_id': user_id},
            UpdateExpression="SET tokens = if_not_exists(tokens, :zero) + :amount",
            ExpressionAttributeValues={':amount': amount, ':zero': 0}
        )
    except Exception as e:
        print(f"Error updating user tokens: {e}")

def send_interaction_response(interaction_id, interaction_token, data):
    url = f"https://discord.com/api/v10/interactions/{interaction_id}/{interaction_token}/callback"
    headers = {
        "Content-Type": "application/json"
    }
    try:
        response = requests.post(url, json=data, headers=headers)
        response.raise_for_status()
        return {
            'statusCode': response.status_code,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*',
            },
            'body': response.text
        }
    except requests.RequestException as e:
        print(f"Error sending interaction response: {e}")
        return error_response(500, 'Failed to send interaction response')

def send_dm_with_embed(user_id, item, price):
    url = f"https://discord.com/api/v10/users/@me/channels"
    headers = {
        "Authorization": f"Bot {BOT_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "recipient_id": user_id
    }
    try:
        # Create a DM channel with the user
        response = requests.post(url, json=payload, headers=headers)
        response.raise_for_status()
        channel_id = response.json()['id']

        dm_url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
        embed = {
            "title": "Transaction Receipt",
            "description": f"You have successfully bought **{item}** for **{price} tokens**.",
            "color": 0x00ff00,  # Embed color in hexadecimal
            "fields": [
                {
                    "name": "Instructions",
                    "value": "Please screenshot this message and show it to our staff to claim your item."
                }
            ]
        }
        dm_payload = {
            "embeds": [embed]  # Embeds should be an array
        }
        # Send the DM with the embed
        dm_response = requests.post(dm_url, json=dm_payload, headers=headers)
        dm_response.raise_for_status()
        print(f"DM sent to user {user_id} with embed: {embed}")
    except requests.RequestException as e:
        print(f"Error sending DM with embed to user {user_id}: {e}")

# Note: register_commands() should be run separately during deployment or manually, not within Lambda handler

def register_commands():
    try:
        if not BOT_TOKEN or not APPLICATION_ID:
            raise ValueError("Bot token or application ID is not set")

        url = f"https://discord.com/api/v10/applications/{APPLICATION_ID}/commands"

        commands = [
            {
                "name": "balance",
                "type": 1,
                "description": "Check your token balance"
            },
            {
                "name": "earn",
                "type": 1,
                "description": "Earn tokens",
                "options": [
                    {
                        "name": "amount",
                        "description": "Amount of tokens to earn",
                        "type": 4,  # INTEGER
                        "required": True
                    }
                ]
            },
            {
                "name": "spend",
                "type": 1,
                "description": "Spend tokens",
                "options": [
                    {
                        "name": "amount",
                        "description": "Amount of tokens to spend",
                        "type": 4,  # INTEGER
                        "required": True
                    }
                ]
            },
            {
                "name": "shop",
                "type": 1,
                "description": "View shop items"
            },
            {
                "name": "buy",
                "type": 1,
                "description": "Buy an item from the shop",
                "options": [
                    {
                        "name": "Item 1 (10 tokens)",
                        "value": "item1"
                    },
                    {
                        "name": "Item 2 (20 tokens)",
                        "value": "item2"
                    },
                    {
                        "name": "Item 3 (30 tokens)",
                        "value": "item3"
                    }
                ]
            },
            {
                "name": "submit_image",
                "type": 1,
                "description": "Submit an image for analysis",
                "options": [
                    {
                        "name": "url",
                        "description": "URL of the image to analyze",
                        "type": 3,  # STRING
                        "required": True
                    }
                ]
            }
        ]

        headers = {
            "Authorization": f"Bot {BOT_TOKEN}",
            "Content-Type": "application/json"
        }

        for command in commands:
            while True:
                response = requests.post(url, json=command, headers=headers)
                # Handle rate limiting
                if response.status_code == 429:
                    retry_after = int(response.headers.get("Retry-After", 1))
                    print(f"Rate limited. Retrying after {retry_after} seconds.")
                else:
                    response.raise_for_status()
                    print(f"Command '{command['name']}' registered successfully")
                    break

    except ValueError as e:
        print(f"Configuration error: {e}")
    except requests.RequestException as e:
        print(f"Error registering commands: {e}")

def encode_image(image_bytes):
    return base64.b64encode(image_bytes).decode('utf-8')

def download_image(url):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        if 'image' not in response.headers.get('Content-Type', ''):
            raise ValueError(f"Unexpected content type: {response.headers.get('Content-Type')}")
        return response.content
    except requests.exceptions.RequestException as e:
        print(f"Error downloading image with requests: {e}")
        print(f"Response status code: {response.status_code}")
        print(f"Response content: {response.text}")
        
        # Fallback to urllib
        return download_image_with_urllib(url)

def download_image_with_urllib(url):
    import urllib.request
    from urllib.error import URLError

    try:
        with urllib.request.urlopen(url) as response:
            return response.read()
    except URLError as e:
        print(f"Error downloading image with urllib: {e}")
        raise

def submit_image_command(body_json, interaction_id, interaction_token, api_key):
    try:
        user_id = body_json['member']['user']['id']
        attachment_url = body_json['data']['options'][0]['value']
      
        image_bytes = download_image(attachment_url)
        base64_image = encode_image(image_bytes)
      
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }

        payload = {
            "model": "gpt-3.5-turbo",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                "Determine the waste in this image and provide the respective tokens to the user:\n\n"
                                "Plastic Waste (1 token):\n"
                                "Plastic bottles\n"
                                "Plastic bags\n"
                                "Food packaging\n"
                                "Straws\n\n"
                                "Paper Waste (1 token):\n"
                                "Newspapers\n"
                                "Magazines\n"
                                "Office paper\n"
                                "Cardboard\n\n"
                                "Glass Waste (2 tokens):\n"
                                "Glass bottles\n"
                                "Jars\n"
                                "Broken glass\n\n"
                                "Metal Waste (3 tokens):\n"
                                "Aluminum cans\n"
                                "Tin cans\n"
                                "Scrap metal\n\n"
                                "Organic Waste (1 token):\n"
                                "Food scraps\n"
                                "Fruit and vegetable peels\n"
                                "Coffee grounds\n"
                                "Yard clippings\n\n"
                                "Textile Waste (2 tokens):\n"
                                "Old clothes\n"
                                "Fabric scraps\n"
                                "Shoes\n\n"
                                "Electronic Waste (E-Waste) (4 tokens):\n"
                                "Old phones\n"
                                "Computers\n"
                                "Batteries\n"
                                "Chargers\n\n"
                                "Wood Waste (2 tokens):\n"
                                "Furniture\n"
                                "Wooden pallets\n"
                                "Tree branches\n\n"
                                "Rubber Waste (3 tokens):\n"
                                "Old tires\n"
                                "Rubber bands\n"
                                "Rubber mats\n\n"
                                "Ceramic Waste (2 tokens):\n"
                                "Broken dishes\n"
                                "Tiles\n"
                                "Pottery\n\n"
                                "Composite Waste (2 tokens):\n"
                                "Tetra packs (juice boxes)\n"
                                "Mixed-material packaging\n\n"
                                "Hazardous Household Waste (5 tokens):\n"
                                "Paints and solvents\n"
                                "Pesticides\n"
                                "Cleaning agents\n"
                                "Fluorescent bulbs\n\n"
                                "Medical Waste (4 tokens):\n"
                                "Used bandages\n"
                                "Syringes\n"
                                "Expired medications\n\n"
                                "Miscellaneous Waste (1 token):\n"
                                "Disposable diapers\n"
                                "Cigarette butts\n"
                                "Styrofoam product"
                            )
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{base64_image}"
                            }
                        }
                    ]
                }
            ],
            "max_tokens": 300
        }
        response = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload)
        response.raise_for_status()
      
        result = response.json()
        description = result['choices'][0]['message']['content']
        
        # Extract token amount from the description
        token_amount = extract_tokens_from_description(description)
        update_user_tokens(user_id, token_amount)
        new_balance = get_user_tokens(user_id)
        
        return send_interaction_response(interaction_id, interaction_token, {
            'type': 4,
            'data': {
                'content': f"<@{user_id}>, here is what I found in the image:\n{description}\nYou have earned {token_amount} tokens. Your new balance is {new_balance} tokens."
            }
        })
    except requests.exceptions.HTTPError as e:
        print(f"HTTP error during API call: {e}")
        print(f"Response content: {e.response.text}")
        return error_response(500, 'Failed to analyze the image')
    except requests.exceptions.RequestException as e:
        print(f"Error during API call: {e}")
        return error_response(500, 'Failed to analyze the image')
    except KeyError as e:
        print(f"Error in API response structure: {e}")
        return error_response(500, 'Failed to process the image')
    except Exception as e:
        print(f"Unhandled error in submit_image_command: {e}")
        return error_response(500, 'Failed to analyze the image')

def extract_tokens_from_description(description):
    # This function should parse the description and determine the total tokens earned based on the waste types
    token_amount = 0
    token_mapping = {
        "Plastic": 1,
        "Paper": 1,
        "Glass": 2,
        "Metal": 3,
        "Organic": 1,
        "Textile": 2,
        "Electronic": 4,
        "Wood": 2,
        "Rubber": 3,
        "Ceramic": 2,
        "Composite": 2,
        "Hazardous": 5,
        "Medical": 4,
        "Miscellaneous": 1
    }
    for waste_type, tokens in token_mapping.items():
        if waste_type in description:
            token_amount += tokens
    return token_amount