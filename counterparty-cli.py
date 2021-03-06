#! /usr/bin/env python3

import os
import argparse
import decimal
import logging
logger = logging.getLogger(__name__)
import time
import dateutil.parser
import calendar
import configparser
import binascii

import appdirs
from prettytable import PrettyTable

from lib import config, util, exceptions, backend, database, transaction, script, api
if os.name == 'nt':
    from lib import util_windows

D = decimal.Decimal

class ConfigurationError(Exception):
    pass

def get_address(address):
    address_dict = {}
    address_dict['balances'] = util.api('get_balances', {'filters': [('address', '==', address),]})
    address_dict['debits'] = util.api('get_debits', {'filters': [('address', '==', address),]})
    address_dict['credits'] = util.api('get_credits', {'filters': [('address', '==', address),]})
    address_dict['burns'] = util.api('get_burns', {'filters': [('source', '==', address),]})
    address_dict['sends'] = util.api('get_sends', {'filters': [('source', '==', address), ('destination', '==', address)], 'filterop': 'or'})
    address_dict['orders'] = util.api('get_orders', {'filters': [('source', '==', address),]})
    address_dict['order_matches'] = util.api('get_order_matches', {'filters': [('tx0_address', '==', address), ('tx1_address', '==', address)], 'filterop': 'or'})
    address_dict['btcpays'] = util.api('get_btcpays', {'filters': [('source', '==', address), ('destination', '==', address)], 'filterop': 'or'})
    address_dict['issuances'] = util.api('get_issuances', {'filters': [('source', '==', address),]})
    address_dict['broadcasts'] = util.api('get_broadcasts', {'filters': [('source', '==', address),]})
    address_dict['bets'] = util.api('get_bets', {'filters': [('source', '==', address),]})
    address_dict['bet_matches'] = util.api('get_bet_matches', {'filters': [('tx0_address', '==', address), ('tx1_address', '==', address)], 'filterop': 'or'})
    address_dict['dividends'] = util.api('get_dividends', {'filters': [('source', '==', address),]})
    address_dict['cancels'] = util.api('get_cancels', {'filters': [('source', '==', address),]})
    address_dict['rps'] = util.api('get_rps', {'filters': [('source', '==', address),]})
    address_dict['rps_matches'] = util.api('get_rps_matches', {'filters': [('tx0_address', '==', address), ('tx1_address', '==', address)], 'filterop': 'or'})
    address_dict['bet_expirations'] = util.api('get_bet_expirations', {'filters': [('source', '==', address),]})
    address_dict['order_expirations'] = util.api('get_order_expirations', {'filters': [('source', '==', address),]})
    address_dict['rps_expirations'] = util.api('get_rps_expirations', {'filters': [('source', '==', address),]})
    address_dict['bet_match_expirations'] = util.api('get_bet_match_expirations', {'filters': [('tx0_address', '==', address), ('tx1_address', '==', address)], 'filterop': 'or'})
    address_dict['order_match_expirations'] = util.api('get_order_match_expirations', {'filters': [('tx0_address', '==', address), ('tx1_address', '==', address)], 'filterop': 'or'})
    address_dict['rps_match_expirations'] = util.api('get_rps_match_expirations', {'filters': [('tx0_address', '==', address), ('tx1_address', '==', address)], 'filterop': 'or'})
    return address_dict

def format_order(order):
    give_quantity = util.value_out(db, D(order['give_quantity']), order['give_asset'])
    get_quantity = util.value_out(db, D(order['get_quantity']), order['get_asset'])
    give_remaining = util.value_out(db, D(order['give_remaining']), order['give_asset'])
    get_remaining = util.value_out(db, D(order['get_remaining']), order['get_asset'])
    give_asset = order['give_asset']
    get_asset = order['get_asset']

    if get_asset < give_asset:
        price = util.value_out(db, D(order['get_quantity']) / D(order['give_quantity']), 'price')
        price_assets = get_asset + '/' + give_asset + ' ask'
    else:
        price = util.value_out(db, D(order['give_quantity']) / D(order['get_quantity']), 'price')
        price_assets = give_asset + '/' + get_asset + ' bid'

    return [D(give_remaining), give_asset, price, price_assets, str(order['fee_required'] / config.UNIT), str(order['fee_provided'] / config.UNIT), order['expire_index'] - util.last_block(db)['block_index'], order['tx_hash']]

def format_bet(bet):
    odds = D(bet['counterwager_quantity']) / D(bet['wager_quantity'])

    if not bet['target_value']:
        target_value = None
    else:
        target_value = bet['target_value']
    if not bet['leverage']:
        leverage = None
    else:
        leverage = util.value_out(db, D(bet['leverage']) / 5040, 'leverage')

    return [util.BET_TYPE_NAME[bet['bet_type']], bet['feed_address'], util.isodt(bet['deadline']), target_value, leverage, str(bet['wager_remaining'] / config.UNIT) + ' XCP', util.value_out(db, odds, 'odds'), bet['expire_index'] - util.last_block(db)['block_index'], bet['tx_hash']]

def format_order_match(db, order_match):
    order_match_id = util.make_id(order_match['tx0_hash'], order_match['tx1_hash'])
    order_match_time_left = order_match['match_expire_index'] - util.last_block(db)['block_index']
    return [order_match_id, order_match_time_left]

def format_feed(feed):
    timestamp = util.isodt(feed['timestamp'])
    if not feed['text']:
        text = '<Locked>'
    else:
        text = feed['text']
    return [feed['source'], timestamp, text, feed['value'], D(feed['fee_fraction_int']) / D(1e8)]

def market(give_asset, get_asset):

    # Your Pending Orders Matches.
    addresses = []
    for bunch in backend.get_wallet(proxy):
        addresses.append(bunch[:2][0])
    filters = [
        ('tx0_address', 'IN', addresses),
        ('tx1_address', 'IN', addresses)
    ]
    awaiting_btcs = util.api('get_order_matches', {'filters': filters, 'filterop': 'OR', 'status': 'pending'})
    table = PrettyTable(['Matched Order ID', 'Time Left'])
    for order_match in awaiting_btcs:
        order_match = format_order_match(db, order_match)
        table.add_row(order_match)
    print('Your Pending Order Matches')
    print(table)
    print('\n')

    # Open orders.
    orders = util.api('get_orders', {'status': 'open'})
    table = PrettyTable(['Give Quantity', 'Give Asset', 'Price', 'Price Assets', 'Required {} Fee'.format(config.BTC), 'Provided {} Fee'.format(config.BTC), 'Time Left', 'Tx Hash'])
    for order in orders:
        if give_asset and order['give_asset'] != give_asset:
            continue
        if get_asset and order['get_asset'] != get_asset:
            continue
        order = format_order(order)
        table.add_row(order)
    print('Open Orders')
    table = table.get_string(sortby='Price')
    print(table)
    print('\n')

    # Open bets.
    bets = util.api('get_bets', {'status': 'open'})
    table = PrettyTable(['Bet Type', 'Feed Address', 'Deadline', 'Target Value', 'Leverage', 'Wager', 'Odds', 'Time Left', 'Tx Hash'])
    for bet in bets:
        bet = format_bet(bet)
        table.add_row(bet)
    print('Open Bets')
    print(table)
    print('\n')

    # Feeds
    broadcasts = util.api('get_broadcasts', {'status': 'valid', 'order_by': 'timestamp', 'order_dir': 'desc'})
    table = PrettyTable(['Feed Address', 'Timestamp', 'Text', 'Value', 'Fee Fraction'])
    seen_addresses = []
    for broadcast in broadcasts:
        # Only show feeds with broadcasts in the last two weeks.
        last_block_time = util.last_block(db)['block_time']
        if broadcast['timestamp'] + config.TWO_WEEKS < last_block_time:
            continue
        # Always show only the latest broadcast from a feed address.
        if broadcast['source'] not in seen_addresses:
            feed = format_feed(broadcast)
            table.add_row(feed)
            seen_addresses.append(broadcast['source'])
        else:
            continue
    print('Feeds')
    print(table)

def get_pubkey(pubkeyhash):
    if backend.is_valid(proxy, pubkeyhash):

        # If in wallet, get from wallet.
        if backend.is_mine(proxy, pubkeyhash):
            return util.hexlify(backend.wallet_pubkeyhash_to_pubkey(proxy, pubkeyhash))

        # If in blockchain (and not in wallet), get from blockchain.
        try:
            return backend.pubkeyhash_to_pubkey(proxy, pubkeyhash, provided_pubkeys=None)
        except script.AddressError:
            pass

        # If not in wallet and not in blockchain, get from user.
        answer = input('Public keys (hexadecimal) or Private key (Wallet Import Format) for `{}`: '.format(pub))
        if script.is_fully_valid(binascii.unhexlify(answer)):
            pubkey = answer
        else:
            private_key = answer
            pubkey = script.private_key_to_public_key(private_key)
        if pubkeyhash != script.pubkey_to_pubkeyhash(binascii.unhexlify(bytes(pubkey, 'utf-8'))):
            raise transaction.InputError('provided public or private key does not match the source address')

        return pubkey

    return None

def cli(method, params, unsigned):

    # Get provided pubkeys from params.
    pubkeys = []
    for address_name in ['source', 'destination']:
        if address_name in params:
            address = params[address_name]
            if script.is_multisig(address):
                _, pubs, _ = script.extract_array(address)
                for pub in pubs:
                    pubkey = get_pubkey(pub)
                    if pubkey:
                        pubkeys.append(pubkey)
            elif address_name != 'destination': # We don’t need the pubkey for a monosig destination.
                pubkey = get_pubkey(address)
                if pubkey:
                    pubkeys.append(pubkey)
    params['pubkey'] = pubkeys

    # Get unsigned transaction serialisation.
    """  # NOTE: For debugging, e.g. with `Invalid Params` error.
    tx_info = sys.modules['lib.send'].compose(db, params['source'], params['destination'], params['asset'], params['quantity'])
    print(transaction.construct(db, proxy, tx_info, encoding=params['encoding'],
                                        fee_per_kb=params['fee_per_kb'],
                                        regular_dust_size=params['regular_dust_size'],
                                        multisig_dust_size=params['multisig_dust_size'],
                                        op_return_value=params['op_return_value'],
                                        provided_pubkeys=params['pubkey'],
                                        allow_unconfirmed_inputs=params['allow_unconfirmed_inputs']))
    exit(0)"""
    unsigned_tx_hex = util.api(method, params)
    print('Transaction (unsigned):', unsigned_tx_hex)

    # Ask to sign and broadcast (if not multi‐sig).
    if script.is_multisig(params['source']):
        print('Multi‐signature transactions are signed and broadcasted manually.')
    elif not unsigned and input('Sign and broadcast? (y/N) ') == 'y':
        if backend.is_mine(proxy, source):
            private_key_wif = None
        elif not private_key_wif:   # If private key was not given earlier.
            private_key_wif = input('Private key (Wallet Import Format): ')

        # Sign and broadcast.
        signed_tx_hex = transaction.sign_tx(proxy, unsigned_tx_hex, private_key_wif=private_key_wif)
        print('Transaction (signed):', signed_tx_hex)
        print('Hash of transaction (broadcasted):', transaction.broadcast_tx(proxy, signed_tx_hex))

def set_options(data_dir=None, backend_rpc_connect=None,
                 backend_rpc_port=None, backend_rpc_user=None, backend_rpc_password=None,
                 backend_rpc_ssl=False, backend_rpc_ssl_verify=True,
                 blockchain_service_name=None, blockchain_service_connect=None,
                 rpc_host=None, rpc_port=None, rpc_user=None,
                 rpc_password=None, rpc_allow_cors=None, log_file=None,
                 config_file=None, database_file=None, testnet=False,
                 testcoin=False, force=False,
                 broadcast_tx_mainnet=None):

    if force:
        config.FORCE = force
    else:
        config.FORCE = False

    # Data directory
    if not data_dir:
        config.DATA_DIR = appdirs.user_config_dir(appauthor=config.XCP_NAME, appname=config.XCP_CLIENT, roaming=True)
    else:
        config.DATA_DIR = os.path.expanduser(data_dir)
    if not os.path.isdir(config.DATA_DIR):
        os.mkdir(config.DATA_DIR)

    # Configuration file
    configfile = configparser.ConfigParser()
    if config_file:
        config_path = config_file
    else:
        config_path = os.path.join(config.DATA_DIR, '{}.conf'.format(config.XCP_CLIENT))
    configfile.read(config_path)
    has_config = 'Default' in configfile
    #logger.debug("Config file: %s; Exists: %s" % (config_path, "Yes" if has_config else "No"))

    # testnet
    if testnet:
        config.TESTNET = testnet
    elif has_config and 'testnet' in configfile['Default']:
        config.TESTNET = configfile['Default'].getboolean('testnet')
    else:
        config.TESTNET = False

    # testcoin
    if testcoin:
        config.TESTCOIN = testcoin
    elif has_config and 'testcoin' in configfile['Default']:
        config.TESTCOIN = configfile['Default'].getboolean('testcoin')
    else:
        config.TESTCOIN = False

    ##############
    # THINGS WE CONNECT TO

    # Backend RPC host (Bitcoin Core)
    if backend_rpc_connect:
        config.BACKEND_RPC_CONNECT = backend_rpc_connect
    elif has_config and 'backend-rpc-connect' in configfile['Default'] and configfile['Default']['backend-rpc-connect']:
        config.BACKEND_RPC_CONNECT = configfile['Default']['backend-rpc-connect']
    elif has_config and 'bitcoind-rpc-connect' in configfile['Default'] and configfile['Default']['bitcoind-rpc-connect']:
        config.BACKEND_RPC_CONNECT = configfile['Default']['bitcoind-rpc-connect']
    else:
        config.BACKEND_RPC_CONNECT = 'localhost'

    # Backend Core RPC port (Bitcoin Core)
    if backend_rpc_port:
        config.BACKEND_RPC_PORT = backend_rpc_port
    elif has_config and 'backend-rpc-port' in configfile['Default'] and configfile['Default']['backend-rpc-port']:
        config.BACKEND_RPC_PORT = configfile['Default']['backend-rpc-port']
    elif has_config and 'bitcoind-rpc-port' in configfile['Default'] and configfile['Default']['bitcoind-rpc-port']:
        config.BACKEND_RPC_PORT = configfile['Default']['bitcoind-rpc-port']
    else:
        if config.TESTNET:
            config.BACKEND_RPC_PORT = config.DEFAULT_BACKEND_RPC_PORT_TESTNET
        else:
            config.BACKEND_RPC_PORT = config.DEFAULT_BACKEND_RPC_PORT
    try:
        config.BACKEND_RPC_PORT = int(config.BACKEND_RPC_PORT)
        if not (int(config.BACKEND_RPC_PORT) > 1 and int(config.BACKEND_RPC_PORT) < 65535):
            raise ConfigurationError('invalid backend API port number')
    except:
        raise Exception("Please specific a valid port number backend-rpc-port configuration parameter")

    # Backend Core RPC user (Bitcoin Core)
    if backend_rpc_user:
        config.BACKEND_RPC_USER = backend_rpc_user
    elif has_config and 'backend-rpc-user' in configfile['Default'] and configfile['Default']['backend-rpc-user']:
        config.BACKEND_RPC_USER = configfile['Default']['backend-rpc-user']
    elif has_config and 'bitcoind-rpc-user' in configfile['Default'] and configfile['Default']['bitcoind-rpc-user']:
        config.BACKEND_RPC_USER = configfile['Default']['bitcoind-rpc-user']
    else:
        config.BACKEND_RPC_USER = 'bitcoinrpc'

    # Backend Core RPC password (Bitcoin Core)
    if backend_rpc_password:
        config.BACKEND_RPC_PASSWORD = backend_rpc_password
    elif has_config and 'backend-rpc-password' in configfile['Default'] and configfile['Default']['backend-rpc-password']:
        config.BACKEND_RPC_PASSWORD = configfile['Default']['backend-rpc-password']
    elif has_config and 'bitcoind-rpc-password' in configfile['Default'] and configfile['Default']['bitcoind-rpc-password']:
        config.BACKEND_RPC_PASSWORD = configfile['Default']['bitcoind-rpc-password']
    else:
        raise ConfigurationError('backend RPC password not set. (Use configuration file or --backend-rpc-password=PASSWORD)')

    # Backend Core RPC SSL
    if backend_rpc_ssl:
        config.BACKEND_RPC_SSL = backend_rpc_ssl
    elif has_config and 'backend-rpc-ssl' in configfile['Default'] and configfile['Default']['backend-rpc-ssl']:
        config.BACKEND_RPC_SSL = configfile['Default']['backend-rpc-ssl']
    else:
        config.BACKEND_RPC_SSL = False  # Default to off.

    # Backend Core RPC SSL Verify
    if backend_rpc_ssl_verify:
        config.BACKEND_RPC_SSL_VERIFY = backend_rpc_ssl_verify
    elif has_config and 'backend-rpc-ssl-verify' in configfile['Default'] and configfile['Default']['backend-rpc-ssl-verify']:
        config.BACKEND_RPC_SSL_VERIFY = configfile['Default']['backend-rpc-ssl-verify']
    else:
        config.BACKEND_RPC_SSL_VERIFY = False # Default to off (support self‐signed certificates)

    # Construct backend URL.
    config.BACKEND_RPC = config.BACKEND_RPC_USER + ':' + config.BACKEND_RPC_PASSWORD + '@' + config.BACKEND_RPC_CONNECT + ':' + str(config.BACKEND_RPC_PORT)
    if config.BACKEND_RPC_SSL:
        config.BACKEND_RPC = 'https://' + config.BACKEND_RPC
    else:
        config.BACKEND_RPC = 'http://' + config.BACKEND_RPC

    # blockchain service name
    if blockchain_service_name:
        config.BLOCKCHAIN_SERVICE_NAME = blockchain_service_name
    elif has_config and 'blockchain-service-name' in configfile['Default'] and configfile['Default']['blockchain-service-name']:
        config.BLOCKCHAIN_SERVICE_NAME = configfile['Default']['blockchain-service-name']
    else:
        config.BLOCKCHAIN_SERVICE_NAME = 'jmcorgan'

    # custom blockchain service API endpoint
    # leave blank to use the default. if specified, include the scheme prefix and port, without a trailing slash (e.g. http://localhost:3001)
    if blockchain_service_connect:
        config.BLOCKCHAIN_SERVICE_CONNECT = blockchain_service_connect
    elif has_config and 'blockchain-service-connect' in configfile['Default'] and configfile['Default']['blockchain-service-connect']:
        config.BLOCKCHAIN_SERVICE_CONNECT = configfile['Default']['blockchain-service-connect']
    else:
        config.BLOCKCHAIN_SERVICE_CONNECT = None #use default specified by the library


    ##############
    # THINGS WE SERVE

    # counterpartyd API RPC host
    if rpc_host:
        config.RPC_HOST = rpc_host
    elif has_config and 'rpc-host' in configfile['Default'] and configfile['Default']['rpc-host']:
        config.RPC_HOST = configfile['Default']['rpc-host']
    else:
        config.RPC_HOST = 'localhost'

    # counterpartyd API RPC port
    if rpc_port:
        config.RPC_PORT = rpc_port
    elif has_config and 'rpc-port' in configfile['Default'] and configfile['Default']['rpc-port']:
        config.RPC_PORT = configfile['Default']['rpc-port']
    else:
        if config.TESTNET:
            if config.TESTCOIN:
                config.RPC_PORT = config.DEFAULT_RPC_PORT_TESTNET + 1
            else:
                config.RPC_PORT = config.DEFAULT_RPC_PORT_TESTNET
        else:
            if config.TESTCOIN:
                config.RPC_PORT = config.DEFAULT_RPC_PORT + 1
            else:
                config.RPC_PORT = config.DEFAULT_RPC_PORT
    try:
        config.RPC_PORT = int(config.RPC_PORT)
        if not (int(config.BACKEND_RPC_PORT) > 1 and int(config.BACKEND_RPC_PORT) < 65535):
            raise ConfigurationError('invalid counterpartyd API port number')
    except:
        raise Exception("Please specific a valid port number rpc-port configuration parameter")

    #  counterpartyd API RPC user
    if rpc_user:
        config.RPC_USER = rpc_user
    elif has_config and 'rpc-user' in configfile['Default'] and configfile['Default']['rpc-user']:
        config.RPC_USER = configfile['Default']['rpc-user']
    else:
        config.RPC_USER = 'rpc'

    #  counterpartyd API RPC password
    if rpc_password:
        config.RPC_PASSWORD = rpc_password
    elif has_config and 'rpc-password' in configfile['Default'] and configfile['Default']['rpc-password']:
        config.RPC_PASSWORD = configfile['Default']['rpc-password']
    else:
        raise ConfigurationError('RPC password not set. (Use configuration file or --rpc-password=PASSWORD)')

    config.RPC = 'http://' + config.RPC_USER + ':' + config.RPC_PASSWORD + '@' + config.RPC_HOST + ':' + str(config.RPC_PORT)

     # RPC CORS
    if rpc_allow_cors:
        config.RPC_ALLOW_CORS = rpc_allow_cors
    elif has_config and 'rpc-allow-cors' in configfile['Default'] and configfile['Default']['rpc-allow-cors']:
        config.RPC_ALLOW_CORS = configfile['Default'].getboolean('rpc-allow-cors')
    else:
        config.RPC_ALLOW_CORS = True

    ##############
    # OTHER SETTINGS

    # Log
    if log_file:
        config.LOG = log_file
    elif has_config and 'log-file' in configfile['Default'] and configfile['Default']['log-file']:
        config.LOG = configfile['Default']['log-file']
    else:
        string = config.XCP_CLIENT
        if config.TESTNET:
            string += '.testnet'
        if config.TESTCOIN:
            string += '.testcoin'
        config.LOG = os.path.join(config.DATA_DIR, string + '.log')

    # Encoding
    if config.TESTCOIN:
        config.PREFIX = b'XX'                   # 2 bytes (possibly accidentally created)
    else:
        config.PREFIX = b'CNTRPRTY'             # 8 bytes

    # Database
    if database_file:
        config.DATABASE = database_file
    elif has_config and 'database-file' in configfile['Default'] and configfile['Default']['database-file']:
        config.DATABASE = configfile['Default']['database-file']
    else:
        string = '{}.'.format(config.XCP_CLIENT) + str(config.VERSION_MAJOR)
        if config.TESTNET:
            string += '.testnet'
        if config.TESTCOIN:
            string += '.testcoin'
        config.DATABASE = os.path.join(config.DATA_DIR, string + '.db')

    # (more) Testnet
    if config.TESTNET:
        config.MAGIC_BYTES = config.MAGIC_BYTES_TESTNET
        if config.TESTCOIN:
            config.ADDRESSVERSION = config.ADDRESSVERSION_TESTNET
            config.BLOCK_FIRST = config.BLOCK_FIRST_TESTNET_TESTCOIN
            config.BURN_START = config.BURN_START_TESTNET_TESTCOIN
            config.BURN_END = config.BURN_END_TESTNET_TESTCOIN
            config.UNSPENDABLE = config.UNSPENDABLE_TESTNET
        else:
            config.ADDRESSVERSION = config.ADDRESSVERSION_TESTNET
            config.BLOCK_FIRST = config.BLOCK_FIRST_TESTNET
            config.BURN_START = config.BURN_START_TESTNET
            config.BURN_END = config.BURN_END_TESTNET
            config.UNSPENDABLE = config.UNSPENDABLE_TESTNET
    else:
        config.MAGIC_BYTES = config.MAGIC_BYTES_MAINNET
        if config.TESTCOIN:
            config.ADDRESSVERSION = config.ADDRESSVERSION_MAINNET
            config.BLOCK_FIRST = config.BLOCK_FIRST_MAINNET_TESTCOIN
            config.BURN_START = config.BURN_START_MAINNET_TESTCOIN
            config.BURN_END = config.BURN_END_MAINNET_TESTCOIN
            config.UNSPENDABLE = config.UNSPENDABLE_MAINNET
        else:
            config.ADDRESSVERSION = config.ADDRESSVERSION_MAINNET
            config.BLOCK_FIRST = config.BLOCK_FIRST_MAINNET
            config.BURN_START = config.BURN_START_MAINNET
            config.BURN_END = config.BURN_END_MAINNET
            config.UNSPENDABLE = config.UNSPENDABLE_MAINNET

    # method used to broadcast signed transactions. bitcoind or bci (default: bitcoind)
    if broadcast_tx_mainnet:
        config.BROADCAST_TX_MAINNET = broadcast_tx_mainnet
    elif has_config and 'broadcast-tx-mainnet' in configfile['Default']:
        config.BROADCAST_TX_MAINNET = configfile['Default']['broadcast-tx-mainnet']
    else:
        config.BROADCAST_TX_MAINNET = '{}'.format(config.BTC_CLIENT)

def balances(address):
    address = script.make_canonical(address)
    script.validate(address)
    balances = get_address(address=address)['balances']
    table = PrettyTable(['Asset', 'Amount'])
    btc_balance = backend.get_btc_balance(address)
    table.add_row([config.BTC, btc_balance])  # BTC
    for balance in balances:
        asset = balance['asset']
        quantity = util.value_out(db, balance['quantity'], balance['asset'])
        table.add_row([asset, quantity])
    print('Balances')
    print(table.get_string())

def generate_move_random_hash(move):
    move = int(move).to_bytes(2, byteorder='big')
    random_bin = os.urandom(16)
    move_random_hash_bin = util.dhash(random_bin + move)
    return binascii.hexlify(random_bin).decode('utf8'), binascii.hexlify(move_random_hash_bin).decode('utf8')


if __name__ == '__main__':
    if os.name == 'nt':
        #patch up cmd.exe's "challenged" (i.e. broken/non-existent) UTF-8 logging
        util_windows.fix_win32_unicode()

    # Parse command-line arguments.
    parser = argparse.ArgumentParser(prog=config.XCP_CLIENT, description='the reference implementation of the {} protocol'.format(config.XCP_NAME))
    parser.add_argument('-V', '--version', action='version', version="{} v{}".format(config.XCP_CLIENT, config.VERSION_STRING))

    parser.add_argument('-v', '--verbose', dest='verbose', action='store_true', help='sets log level to DEBUG instead of WARNING')
    parser.add_argument('--testnet', action='store_true', help='use {} testnet addresses and block numbers'.format(config.BTC_NAME))
    parser.add_argument('--testcoin', action='store_true', help='use the test {} network on every blockchain'.format(config.XCP_NAME))
    parser.add_argument('--unconfirmed', action='store_true', help='allow the spending of unconfirmed transaction outputs')
    parser.add_argument('--encoding', default='auto', type=str, help='data encoding method')
    parser.add_argument('--fee-per-kb', type=D, default=D(config.DEFAULT_FEE_PER_KB / config.UNIT), help='fee per kilobyte, in {}'.format(config.BTC))
    parser.add_argument('--regular-dust-size', type=D, default=D(config.DEFAULT_REGULAR_DUST_SIZE / config.UNIT), help='value for dust Pay‐to‐Pubkey‐Hash outputs, in {}'.format(config.BTC))
    parser.add_argument('--multisig-dust-size', type=D, default=D(config.DEFAULT_MULTISIG_DUST_SIZE / config.UNIT), help='for dust OP_CHECKMULTISIG outputs, in {}'.format(config.BTC))
    parser.add_argument('--op-return-value', type=D, default=D(config.DEFAULT_OP_RETURN_VALUE / config.UNIT), help='value for OP_RETURN outputs, in {}'.format(config.BTC))
    parser.add_argument('--unsigned', action='store_true', help='print out unsigned hex of transaction; do not sign or broadcast')

    parser.add_argument('--data-dir', help='the directory in which to keep the database, config file and log file, by default')
    parser.add_argument('--database-file', help='the location of the SQLite3 database')
    parser.add_argument('--config-file', help='the location of the configuration file')
    parser.add_argument('--log-file', help='the location of the log file')

    parser.add_argument('--backend-rpc-connect', help='the hostname or IP of the backend bitcoind JSON-RPC server')
    parser.add_argument('--backend-rpc-port', type=int, help='the backend JSON-RPC port to connect to')
    parser.add_argument('--backend-rpc-user', help='the username used to communicate with backend over JSON-RPC')
    parser.add_argument('--backend-rpc-password', help='the password used to communicate with backend over JSON-RPC')
    parser.add_argument('--backend-rpc-ssl', action='store_true', help='use SSL to connect to backend (default: false)')
    parser.add_argument('--backend-rpc-ssl-verify', action='store_true', help='verify SSL certificate of backend; disallow use of self‐signed certificates (default: false)')

    parser.add_argument('--blockchain-service-name', help='the blockchain service name to connect to')
    parser.add_argument('--blockchain-service-connect', help='the blockchain service server URL base to connect to, if not default')

    parser.add_argument('--rpc-host', help='the IP of the interface to bind to for providing JSON-RPC API access (0.0.0.0 for all interfaces)')
    parser.add_argument('--rpc-port', type=int, help='port on which to provide the {} JSON-RPC API'.format(config.XCP_CLIENT))
    parser.add_argument('--rpc-user', help='required username to use the {} JSON-RPC API (via HTTP basic auth)'.format(config.XCP_CLIENT))
    parser.add_argument('--rpc-password', help='required password (for rpc-user) to use the {} JSON-RPC API (via HTTP basic auth)'.format(config.XCP_CLIENT))
    parser.add_argument('--rpc-allow-cors', action='store_true', default=True, help='Allow ajax cross domain request')

    subparsers = parser.add_subparsers(dest='action', help='the action to be taken')

    parser_send = subparsers.add_parser('send', help='create and broadcast a *send* message')
    parser_send.add_argument('--source', required=True, help='the source address')
    parser_send.add_argument('--destination', required=True, help='the destination address')
    parser_send.add_argument('--quantity', required=True, help='the quantity of ASSET to send')
    parser_send.add_argument('--asset', required=True, help='the ASSET of which you would like to send QUANTITY')
    parser_send.add_argument('--fee', help='the exact {} fee to be paid to miners'.format(config.BTC))

    parser_order = subparsers.add_parser('order', help='create and broadcast an *order* message')
    parser_order.add_argument('--source', required=True, help='the source address')
    parser_order.add_argument('--get-quantity', required=True, help='the quantity of GET_ASSET that you would like to receive')
    parser_order.add_argument('--get-asset', required=True, help='the asset that you would like to buy')
    parser_order.add_argument('--give-quantity', required=True, help='the quantity of GIVE_ASSET that you are willing to give')
    parser_order.add_argument('--give-asset', required=True, help='the asset that you would like to sell')
    parser_order.add_argument('--expiration', type=int, required=True, help='the number of blocks for which the order should be valid')
    parser_order.add_argument('--fee-fraction-required', default=config.DEFAULT_FEE_FRACTION_REQUIRED, help='the miners’ fee required for an order to match this one, as a fraction of the {} to be bought'.format(config.BTC))
    parser_order_fees = parser_order.add_mutually_exclusive_group()
    parser_order_fees.add_argument('--fee-fraction-provided', default=config.DEFAULT_FEE_FRACTION_PROVIDED, help='the miners’ fee provided, as a fraction of the {} to be sold'.format(config.BTC))
    parser_order_fees.add_argument('--fee', help='the exact {} fee to be paid to miners'.format(config.BTC))

    parser_btcpay = subparsers.add_parser('{}pay'.format(config.BTC).lower(), help='create and broadcast a *{}pay* message, to settle an Order Match for which you owe {}'.format(config.BTC, config.BTC))
    parser_btcpay.add_argument('--source', required=True, help='the source address')
    parser_btcpay.add_argument('--order-match-id', required=True, help='the concatenation of the hashes of the two transactions which compose the order match')
    parser_btcpay.add_argument('--fee', help='the exact {} fee to be paid to miners'.format(config.BTC))

    parser_issuance = subparsers.add_parser('issuance', help='issue a new asset, issue more of an existing asset or transfer the ownership of an asset')
    parser_issuance.add_argument('--source', required=True, help='the source address')
    parser_issuance.add_argument('--transfer-destination', help='for transfer of ownership of asset issuance rights')
    parser_issuance.add_argument('--quantity', default=0, help='the quantity of ASSET to be issued')
    parser_issuance.add_argument('--asset', required=True, help='the name of the asset to be issued (if it’s available)')
    parser_issuance.add_argument('--divisible', action='store_true', help='whether or not the asset is divisible (must agree with previous issuances)')
    parser_issuance.add_argument('--description', type=str, required=True, help='a description of the asset (set to ‘LOCK’ to lock against further issuances with non‐zero quantitys)')
    parser_issuance.add_argument('--fee', help='the exact {} fee to be paid to miners'.format(config.BTC))

    parser_broadcast = subparsers.add_parser('broadcast', help='broadcast textual and numerical information to the network')
    parser_broadcast.add_argument('--source', required=True, help='the source address')
    parser_broadcast.add_argument('--text', type=str, required=True, help='the textual part of the broadcast (set to ‘LOCK’ to lock feed)')
    parser_broadcast.add_argument('--value', type=float, default=-1, help='numerical value of the broadcast')
    parser_broadcast.add_argument('--fee-fraction', default=0, help='the fraction of bets on this feed that go to its operator')
    parser_broadcast.add_argument('--fee', help='the exact {} fee to be paid to miners'.format(config.BTC))

    parser_bet = subparsers.add_parser('bet', help='offer to make a bet on the value of a feed')
    parser_bet.add_argument('--source', required=True, help='the source address')
    parser_bet.add_argument('--feed-address', required=True, help='the address which publishes the feed to bet on')
    parser_bet.add_argument('--bet-type', choices=list(util.BET_TYPE_NAME.values()), required=True, help='choices: {}'.format(list(util.BET_TYPE_NAME.values())))
    parser_bet.add_argument('--deadline', required=True, help='the date and time at which the bet should be decided/settled')
    parser_bet.add_argument('--wager', required=True, help='the quantity of XCP to wager')
    parser_bet.add_argument('--counterwager', required=True, help='the minimum quantity of XCP to be wagered by the user to bet against you, if he were to accept the whole thing')
    parser_bet.add_argument('--target-value', default=0.0, help='target value for Equal/NotEqual bet')
    parser_bet.add_argument('--leverage', type=int, default=5040, help='leverage, as a fraction of 5040')
    parser_bet.add_argument('--expiration', type=int, required=True, help='the number of blocks for which the bet should be valid')
    parser_bet.add_argument('--fee', help='the exact {} fee to be paid to miners'.format(config.BTC))

    parser_dividend = subparsers.add_parser('dividend', help='pay dividends to the holders of an asset (in proportion to their stake in it)')
    parser_dividend.add_argument('--source', required=True, help='the source address')
    parser_dividend.add_argument('--quantity-per-unit', required=True, help='the quantity of XCP to be paid per whole unit held of ASSET')
    parser_dividend.add_argument('--asset', required=True, help='the asset to which pay dividends')
    parser_dividend.add_argument('--dividend-asset', required=True, help='asset in which to pay the dividends')
    parser_dividend.add_argument('--fee', help='the exact {} fee to be paid to miners'.format(config.BTC))

    parser_burn = subparsers.add_parser('burn', help='destroy {} to earn XCP, during an initial period of time')
    parser_burn.add_argument('--source', required=True, help='the source address')
    parser_burn.add_argument('--quantity', required=True, help='quantity of {} to be burned'.format(config.BTC))
    parser_burn.add_argument('--fee', help='the exact {} fee to be paid to miners'.format(config.BTC))

    parser_cancel = subparsers.add_parser('cancel', help='cancel an open order or bet you created')
    parser_cancel.add_argument('--source', required=True, help='the source address')
    parser_cancel.add_argument('--offer-hash', required=True, help='the transaction hash of the order or bet')
    parser_cancel.add_argument('--fee', help='the exact {} fee to be paid to miners'.format(config.BTC))

    parser_rps = subparsers.add_parser('rps', help='open a rock-paper-scissors like game')
    parser_rps.add_argument('--source', required=True, help='the source address')
    parser_rps.add_argument('--wager', required=True, help='the quantity of XCP to wager')
    parser_rps.add_argument('--move', type=int, required=True, help='the selected move')
    parser_rps.add_argument('--possible-moves', type=int, required=True, help='the number of possible moves (odd number greater or equal than 3)')
    parser_rps.add_argument('--expiration', type=int, required=True, help='the number of blocks for which the bet should be valid')
    parser_rps.add_argument('--fee', help='the exact BTC fee to be paid to miners')

    parser_rpsresolve = subparsers.add_parser('rpsresolve', help='resolve a rock-paper-scissors like game')
    parser_rpsresolve.add_argument('--source', required=True, help='the source address')
    parser_rpsresolve.add_argument('--random', type=str, required=True, help='the random number used in the corresponding rps transaction')
    parser_rpsresolve.add_argument('--move', type=int, required=True, help='the selected move in the corresponding rps transaction')
    parser_rpsresolve.add_argument('--rps-match-id', required=True, help='the concatenation of the hashes of the two transactions which compose the rps match')
    parser_rpsresolve.add_argument('--fee', help='the exact BTC fee to be paid to miners')

    parser_publish = subparsers.add_parser('publish', help='publish contract code in the blockchain')
    parser_publish.add_argument('--source', required=True, help='the source address')
    parser_publish.add_argument('--gasprice', required=True, type=int, help='the price of gas')
    parser_publish.add_argument('--startgas', required=True, type=int, help='the maximum quantity of {} to be used to pay for the execution (satoshis)'.format(config.XCP))
    parser_publish.add_argument('--endowment', required=True, type=int, help='quantity of {} to be transfered to the contract (satoshis)'.format(config.XCP))
    parser_publish.add_argument('--code-hex', required=True, type=str, help='the hex‐encoded contract (returned by `serpent compile`)')
    parser_publish.add_argument('--fee', help='the exact {} fee to be paid to miners'.format(config.BTC))

    parser_execute = subparsers.add_parser('execute', help='execute contract code in the blockchain')
    parser_execute.add_argument('--source', required=True, help='the source address')
    parser_execute.add_argument('--contract-id', required=True, help='the contract ID of the contract to be executed')
    parser_execute.add_argument('--gasprice', required=True, type=int, help='the price of gas')
    parser_execute.add_argument('--startgas', required=True, type=int, help='the maximum quantity of {} to be used to pay for the execution (satoshis)'.format(config.XCP))
    parser_execute.add_argument('--value', required=True, type=int, help='quantity of {} to be transfered to the contract (satoshis)'.format(config.XCP))
    parser_execute.add_argument('--payload-hex', required=True, type=str, help='data to be provided to the contract (returned by `serpent encode_datalist`)')
    parser_execute.add_argument('--fee', help='the exact {} fee to be paid to miners'.format(config.BTC))

    parser_destroy = subparsers.add_parser('destroy', help='destroy a quantity of a Counterparty asset')
    parser_destroy.add_argument('--source', required=True, help='the source address')
    parser_destroy.add_argument('--asset', required=True, help='the ASSET of which you would like to destroy QUANTITY')
    parser_destroy.add_argument('--quantity', required=True, help='the quantity of ASSET to destroy')
    parser_destroy.add_argument('--tag', default='', help='tag')
    parser_destroy.add_argument('--fee', help='the exact {} fee to be paid to miners'.format(config.BTC))

    parser_address = subparsers.add_parser('balances', help='display the balances of a {} address'.format(config.XCP_NAME))
    parser_address.add_argument('address', help='the address you are interested in')

    parser_asset = subparsers.add_parser('asset', help='display the basic properties of a {} asset'.format(config.XCP_NAME))
    parser_asset.add_argument('asset', help='the asset you are interested in')

    parser_wallet = subparsers.add_parser('wallet', help='list the addresses in your backend wallet along with their balances in all {} assets'.format(config.XCP_NAME))

    parser_pending = subparsers.add_parser('pending', help='list pending order matches awaiting {}payment from you'.format(config.BTC))

    parser_market = subparsers.add_parser('market', help='fill the screen with an always up-to-date summary of the {} market'.format(config.XCP_NAME))
    parser_market.add_argument('--give-asset', help='only show orders offering to sell GIVE_ASSET')
    parser_market.add_argument('--get-asset', help='only show orders offering to buy GET_ASSET')

    args = parser.parse_args()

    # Convert.
    args.fee_per_kb = int(args.fee_per_kb * config.UNIT)
    args.regular_dust_size = int(args.regular_dust_size * config.UNIT)
    args.multisig_dust_size = int(args.multisig_dust_size * config.UNIT)
    args.op_return_value = int(args.op_return_value * config.UNIT)

    # Hack
    try:
        args.force
    except (NameError, AttributeError):
        args.force = None

    # Configuration
    set_options(data_dir=args.data_dir,
                backend_rpc_connect=args.backend_rpc_connect,
                backend_rpc_port=args.backend_rpc_port,
                backend_rpc_user=args.backend_rpc_user,
                backend_rpc_password=args.backend_rpc_password,
                backend_rpc_ssl=args.backend_rpc_ssl,
                backend_rpc_ssl_verify=args.backend_rpc_ssl_verify,
                blockchain_service_name=args.blockchain_service_name,
                blockchain_service_connect=args.blockchain_service_connect,
                rpc_host=args.rpc_host, rpc_port=args.rpc_port, rpc_user=args.rpc_user,
                rpc_password=args.rpc_password, rpc_allow_cors=args.rpc_allow_cors,
                log_file=args.log_file, config_file=args.config_file,
                database_file=args.database_file, testnet=args.testnet,
                testcoin=args.testcoin, force=args.force)

    # Database
    logger.info('Connecting to database.')
    db = database.get_connection()

    # Proxy
    proxy = backend.get_proxy()

    # MESSAGE CREATION
    if args.action == 'send':
        if args.fee:
            args.fee = util.value_in(db, args.fee, config.BTC)
        quantity = util.value_in(db, args.quantity, args.asset)
        cli('create_send', {'source': args.source,
                            'destination': args.destination, 'asset':
                            args.asset, 'quantity': quantity, 'fee': args.fee,
                            'allow_unconfirmed_inputs': args.unconfirmed,
                            'encoding': args.encoding, 'fee_per_kb':
                            args.fee_per_kb, 'regular_dust_size':
                            args.regular_dust_size, 'multisig_dust_size':
                            args.multisig_dust_size, 'op_return_value':
                            args.op_return_value},
            args.unsigned)

    elif args.action == 'order':
        if args.fee:
            args.fee = util.value_in(db, args.fee, config.BTC)
        fee_required, fee_fraction_provided = D(args.fee_fraction_required), D(args.fee_fraction_provided)
        give_quantity, get_quantity = D(args.give_quantity), D(args.get_quantity)

        # Fee argument is either fee_required or fee_provided, as necessary.
        if args.give_asset == config.BTC:
            fee_required = 0
            fee_fraction_provided = util.value_in(db, fee_fraction_provided, 'fraction')
            fee_provided = round(D(fee_fraction_provided) * D(give_quantity) * D(config.UNIT))
            print('Fee provided: {} {}'.format(util.value_out(db, fee_provided, config.BTC), config.BTC))
        elif args.get_asset == config.BTC:
            fee_provided = 0
            fee_fraction_required = util.value_in(db, args.fee_fraction_required, 'fraction')
            fee_required = round(D(fee_fraction_required) * D(get_quantity) * D(config.UNIT))
            print('Fee required: {} {}'.format(util.value_out(db, fee_required, config.BTC), config.BTC))
        else:
            fee_required = 0
            fee_provided = 0

        give_quantity = util.value_in(db, give_quantity, args.give_asset)
        get_quantity = util.value_in(db, get_quantity, args.get_asset)

        cli('create_order', {'source': args.source,
                             'give_asset': args.give_asset, 'give_quantity':
                             give_quantity, 'get_asset': args.get_asset,
                             'get_quantity': get_quantity, 'expiration':
                             args.expiration, 'fee_required': fee_required,
                             'fee_provided': fee_provided, 'fee': args.fee,
                             'allow_unconfirmed_inputs': args.unconfirmed,
                             'encoding': args.encoding, 'fee_per_kb':
                             args.fee_per_kb, 'regular_dust_size':
                             args.regular_dust_size, 'multisig_dust_size':
                             args.multisig_dust_size, 'op_return_value':
                             args.op_return_value},
           args.unsigned)

    elif args.action == '{}pay'.format(config.BTC).lower():
        if args.fee:
            args.fee = util.value_in(db, args.fee, config.BTC)
        cli('create_btcpay', {'source': args.source,
                              'order_match_id': args.order_match_id, 'fee':
                              args.fee, 'allow_unconfirmed_inputs':
                              args.unconfirmed, 'encoding': args.encoding,
                              'fee_per_kb': args.fee_per_kb,
                              'regular_dust_size': args.regular_dust_size,
                              'multisig_dust_size': args.multisig_dust_size,
                              'op_return_value': args.op_return_value},
            args.unsigned)

    elif args.action == 'issuance':
        if args.fee:
            args.fee = util.value_in(db, args.fee, config.BTC)
        quantity = util.value_in(db, args.quantity, None, divisible=args.divisible)

        cli('create_issuance', {'source': args.source, 'asset': args.asset,
                                'quantity': quantity, 'divisible':
                                args.divisible, 'description':
                                args.description, 'transfer_destination':
                                args.transfer_destination, 'fee': args.fee,
                                'allow_unconfirmed_inputs': args.unconfirmed,
                                'encoding': args.encoding, 'fee_per_kb':
                                args.fee_per_kb, 'regular_dust_size':
                                args.regular_dust_size, 'multisig_dust_size':
                                args.multisig_dust_size, 'op_return_value':
                                args.op_return_value},
           args.unsigned)

    elif args.action == 'broadcast':
        if args.fee:
            args.fee = util.value_in(db, args.fee, config.BTC)
        value = util.value_in(db, args.value, 'value')
        fee_fraction = util.value_in(db, args.fee_fraction, 'fraction')

        cli('create_broadcast', {'source': args.source,
                                 'fee_fraction': fee_fraction, 'text':
                                 args.text, 'timestamp': int(time.time()),
                                 'value': value, 'fee': args.fee,
                                 'allow_unconfirmed_inputs': args.unconfirmed,
                                 'encoding': args.encoding, 'fee_per_kb':
                                 args.fee_per_kb, 'regular_dust_size':
                                 args.regular_dust_size, 'multisig_dust_size':
                                 args.multisig_dust_size, 'op_return_value':
                                 args.op_return_value},
           args.unsigned)

    elif args.action == 'bet':
        if args.fee:
            args.fee = util.value_in(db, args.fee, config.BTC)
        deadline = calendar.timegm(dateutil.parser.parse(args.deadline).utctimetuple())
        wager = util.value_in(db, args.wager, config.XCP)
        counterwager = util.value_in(db, args.counterwager, config.XCP)
        target_value = util.value_in(db, args.target_value, 'value')
        leverage = util.value_in(db, args.leverage, 'leverage')

        cli('create_bet', {'source': args.source,
                           'feed_address': args.feed_address, 'bet_type':
                           util.BET_TYPE_ID[args.bet_type], 'deadline': deadline, 'wager_quantity': wager,
                           'counterwager_quantity': counterwager, 'expiration':
                           args.expiration, 'target_value': target_value,
                           'leverage': leverage, 'fee': args.fee,
                           'allow_unconfirmed_inputs': args.unconfirmed,
                           'encoding': args.encoding, 'fee_per_kb':
                           args.fee_per_kb, 'regular_dust_size':
                           args.regular_dust_size, 'multisig_dust_size':
                           args.multisig_dust_size, 'op_return_value':
                           args.op_return_value},
            args.unsigned)

    elif args.action == 'dividend':
        if args.fee:
            args.fee = util.value_in(db, args.fee, config.BTC)
        quantity_per_unit = util.value_in(db, args.quantity_per_unit, config.XCP)
        cli('create_dividend', {'source': args.source,
                                'quantity_per_unit': quantity_per_unit,
                                'asset': args.asset, 'dividend_asset':
                                args.dividend_asset, 'fee': args.fee,
                                'allow_unconfirmed_inputs': args.unconfirmed,
                                'encoding': args.encoding, 'fee_per_kb':
                                args.fee_per_kb, 'regular_dust_size':
                                args.regular_dust_size, 'multisig_dust_size':
                                args.multisig_dust_size, 'op_return_value':
                                args.op_return_value},
           args.unsigned)

    elif args.action == 'burn':
        if args.fee:
            args.fee = util.value_in(db, args.fee, config.BTC)
        quantity = util.value_in(db, args.quantity, config.BTC)
        cli('create_burn', {'source': args.source, 'quantity': quantity,
                            'fee': args.fee, 'allow_unconfirmed_inputs':
                            args.unconfirmed, 'encoding': args.encoding,
                            'fee_per_kb': args.fee_per_kb, 'regular_dust_size':
                            args.regular_dust_size, 'multisig_dust_size':
                            args.multisig_dust_size, 'op_return_value':
                            args.op_return_value},
        args.unsigned)

    elif args.action == 'cancel':
        if args.fee:
            args.fee = util.value_in(db, args.fee, config.BTC)
        cli('create_cancel', {'source': args.source,
                              'offer_hash': args.offer_hash, 'fee': args.fee,
                              'allow_unconfirmed_inputs': args.unconfirmed,
                              'encoding': args.encoding, 'fee_per_kb':
                              args.fee_per_kb, 'regular_dust_size':
                              args.regular_dust_size, 'multisig_dust_size':
                              args.multisig_dust_size, 'op_return_value':
                              args.op_return_value},
        args.unsigned)

    elif args.action == 'rps':
        if args.fee:
            args.fee = util.value_in(db, args.fee, 'BTC')
        wager = util.value_in(db, args.wager, 'XCP')
        random, move_random_hash = generate_move_random_hash(args.move)
        print('random: {}'.format(random))
        print('move_random_hash: {}'.format(move_random_hash))
        cli('create_rps', {'source': args.source,
                           'possible_moves': args.possible_moves, 'wager': wager,
                           'move_random_hash': move_random_hash, 'expiration': args.expiration,
                           'fee': args.fee, 'allow_unconfirmed_inputs': args.unconfirmed,
                           'encoding': args.encoding, 'fee_per_kb':
                           args.fee_per_kb, 'regular_dust_size':
                           args.regular_dust_size, 'multisig_dust_size':
                           args.multisig_dust_size, 'op_return_value':
                           args.op_return_value},
           args.unsigned)

    elif args.action == 'rpsresolve':
        if args.fee:
            args.fee = util.value_in(db, args.fee, 'BTC')
        cli('create_rpsresolve', {'source': args.source,
                                'random': args.random, 'move': args.move,
                                'rps_match_id': args.rps_match_id, 'fee': args.fee,
                                'allow_unconfirmed_inputs': args.unconfirmed,
                                'encoding': args.encoding, 'fee_per_kb':
                                args.fee_per_kb, 'regular_dust_size':
                                args.regular_dust_size, 'multisig_dust_size':
                                args.multisig_dust_size, 'op_return_value':
                                args.op_return_value},
           args.unsigned)

    elif args.action == 'publish':
        if args.fee:
            args.fee = util.value_in(db, args.fee, 'BTC')
        cli('create_publish', {'source': args.source,
                               'gasprice': args.gasprice, 'startgas':
                               args.startgas, 'endowment': args.endowment,
                               'code_hex': args.code_hex, 'fee': args.fee,
                               'allow_unconfirmed_inputs': args.unconfirmed,
                               'encoding': args.encoding, 'fee_per_kb':
                               args.fee_per_kb, 'regular_dust_size':
                               args.regular_dust_size, 'multisig_dust_size':
                               args.multisig_dust_size, 'op_return_value':
                               args.op_return_value}, args.unsigned)

    elif args.action == 'execute':
        if args.fee:
            args.fee = util.value_in(db, args.fee, 'BTC')
        value = util.value_in(db, args.value, 'XCP')
        startgas = util.value_in(db, args.startgas, 'XCP')
        cli('create_execute', {'source': args.source,
                               'contract_id': args.contract_id, 'gasprice':
                               args.gasprice, 'startgas': args.startgas,
                               'value': value, 'payload_hex': args.payload_hex, 'fee':
                               args.fee, 'allow_unconfirmed_inputs':
                               args.unconfirmed, 'encoding': args.encoding,
                               'fee_per_kb': args.fee_per_kb,
                               'regular_dust_size': args.regular_dust_size,
                               'multisig_dust_size': args.multisig_dust_size,
                               'op_return_value': args.op_return_value},
            args.unsigned)

    elif args.action == 'destroy':
        if args.fee:
            args.fee = util.devise(db, args.fee, config.BTC, 'input')
        quantity = util.devise(db, args.quantity, args.asset, 'input')
        cli('create_destroy', {'source': args.source,
                            'asset': args.asset, 'quantity': quantity, 'tag':
                            args.tag, 'fee': args.fee,
                            'allow_unconfirmed_inputs': args.unconfirmed,
                            'encoding': args.encoding, 'fee_per_kb':
                            args.fee_per_kb, 'regular_dust_size':
                            args.regular_dust_size, 'multisig_dust_size':
                            args.multisig_dust_size, 'op_return_value':
                            args.op_return_value}, args.unsigned)


    # VIEWING (temporary)
    elif args.action == 'balances':
        balances(args.address)

    elif args.action == 'asset':
        results = util.api('get_asset_info', {'assets': [args.asset]})
        if results:
            results = results[0]    # HACK
        else:
            print('Asset ‘{}’ not found.'.format(args.asset))
            exit(0)

        asset_id = util.get_asset_id(db, args.asset, util.last_block(db)['block_index'])
        divisible = results['divisible']
        locked = results['locked']
        supply = util.value_out(db, results['supply'], args.asset)
        call_date = util.isodt(results['call_date']) if results['call_date'] else results['call_date']
        call_price = str(results['call_price']) + ' XCP' if results['call_price'] else results['call_price']

        print('Asset Name:', args.asset)
        print('Asset ID:', asset_id)
        print('Divisible:', divisible)
        print('Locked:', locked)
        print('Supply:', supply)
        print('Issuer:', results['issuer'])
        print('Description:', '‘' + results['description'] + '’')

        if args.asset != config.BTC:
            print('Shareholders:')
            balances = util.api('get_balances', {'filters': [('asset', '==', args.asset)]})
            print('\taddress, quantity, escrow')
            for holder in util.holders(db, args.asset):
                quantity = holder['address_quantity']
                if not quantity:
                    continue
                quantity = util.value_out(db, quantity, args.asset)
                if holder['escrow']:
                    escrow = holder['escrow']
                else:
                    escrow = 'None'
                print('\t' + str(holder['address']) + ',' + str(quantity) + ',' + escrow)


    elif args.action == 'wallet':
        total_table = PrettyTable(['Asset', 'Balance'])
        totals = {}

        print()
        for bunch in backend.get_wallet(proxy):
            address, btc_balance = bunch[:2]
            address_data = get_address(address=address)
            balances = address_data['balances']
            table = PrettyTable(['Asset', 'Balance'])
            empty = True
            if btc_balance:
                table.add_row([config.BTC, btc_balance])  # BTC
                if config.BTC in totals.keys():
                    totals[config.BTC] += btc_balance
                else:
                    totals[config.BTC] = btc_balance
                empty = False
            for balance in balances:
                asset = balance['asset']
                try:
                    balance = D(util.value_out(db, balance['quantity'], balance['asset']))
                except Exception:   # TODO
                    balance = None
                if balance:
                    if asset in totals.keys():
                        totals[asset] += balance
                    else:
                        totals[asset] = balance
                    table.add_row([asset, balance])
                    empty = False
            if not empty:
                print(address)
                print(table.get_string())
                print()
        for asset in totals.keys():
            balance = totals[asset]
            total_table.add_row([asset, round(balance, 8)])
        print('TOTAL')
        print(total_table.get_string())
        print()

    elif args.action == 'pending':
        addresses = []
        for bunch in backend.get_wallet(proxy):
            addresses.append(bunch[:2][0])
        filters = [
            ('tx0_address', 'IN', addresses),
            ('tx1_address', 'IN', addresses)
        ]
        awaiting_btcs = util.api('get_order_matches', {'filters': filters, 'filterop': 'OR', 'status': 'pending'})
        table = PrettyTable(['Matched Order ID', 'Time Left'])
        for order_match in awaiting_btcs:
            order_match = format_order_match(db, order_match)
            table.add_row(order_match)
        print(table)

    elif args.action == 'market':
        market(args.give_asset, args.get_asset)

    else:
        parser.print_help()

# vim: tabstop=8 expandtab shiftwidth=4 softtabstop=4
