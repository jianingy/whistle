#!/usr/bin/env python
# -*- coding: utf-8 -*-
# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2013, jianingy.yang@gmail.com
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from json import loads as json_decode
from json import dumps as json_encode
from os import path
from oslo.config import cfg
from twisted.internet import protocol
from twisted.internet import reactor
from twisted.words.protocols import irc
from whistle import amqp

import logging

__version__ = '0.01'
logger = logging.getLogger(__name__)

cli_opts = [
    cfg.StrOpt('irc-host', dest='irc_host',
               default='hubbard.freenode.net',
               help='The host of irc server'),
    cfg.IntOpt('irc-port', dest='irc_port',
               default=6667,
               help='The port of irc server'),
    cfg.StrOpt('amqp-host', dest='amqp_host',
               default='localhost',
               help='The host of AMQP service'),
    cfg.IntOpt('amqp-port', dest='amqp_port',
               default=5672,
               help='The port of AMQP service'),
    cfg.StrOpt('amqp-user', dest='amqp_user',
               default='guest',
               help='The username of AMQP service'),
    cfg.StrOpt('amqp-password', dest='amqp_password',
               default='guest',
               help='The password of AMQP service'),
    cfg.StrOpt('amqp-send-queue', dest='amqp_send_queue',
               default='whistle.send',
               help='The queue for sending message'),
    cfg.StrOpt('amqp-recv-queue', dest='amqp_recv_queue',
               default='whistle.recv',
               help='The queue for receiving message'),
    cfg.StrOpt('nickname',
               default='whistle007',
               help='The nickname of this bot'),
    cfg.DictOpt('channels',
                default={'ircq': ''},
                help='The channels to join'),
    cfg.DictOpt('encodings',
                default={'ircq': 'utf-8'},
                help='The encodings of each channels'),
]


CONF = cfg.CONF
CONF.register_cli_opts(cli_opts)


class IRCClient(irc.IRCClient):

    versionName = "whistle"
    versionNum = __version__

    ##########################################################################
    # Helper functions
    ##########################################################################

    def __init__(self):
        self.nickname = CONF.nickname
        self.realname = CONF.nickname

    def _decode(self, channel, msg):
        return msg.decode(CONF.encodings.get(channel, 'UTF-8'), 'ignore')

    def _encode(self, channel, msg):
        return msg.encode(CONF.encodings.get(channel, 'UTF-8'), 'ignore')

    def lineReceived(self, line):
        logger.debug(">> %s" % line)
        irc.IRCClient.lineReceived(self, line)

    def sendLine(self, line):
        logger.debug("<< %s" % line)
        irc.IRCClient.sendLine(self, line)

    ##########################################################################
    # Protocol event dealers
    ##########################################################################

    def signedOn(self):
        for channel, password in CONF.channels.items():
            if password:
                self.join(channel, password)
            else:
                self.join(channel)

    def userJoined(self, user, channel):
        pass

    def userLeft(self, user, channel):
        pass

    def joined(self, channel):
        logging.info('channel %s joined' % channel)
        self.factory.amqp_client.read(CONF.amqp_recv_queue, channel,
                                      lambda x: self._send(channel, x))

    def userRenamed(self, oldname, newname):
        pass

    def privmsg(self, user, channel, message):
        data = dict(user=user, channel=channel, message=message)
        self.factory.amqp_client.send_message(exchange=CONF.amqp_send_queue,
                                              routing_key=channel,
                                              msg=json_encode(data))

    def _send(self, channel, message):
        try:
            body = json_decode(message.content.body)
            message = self._encode(channel, body['message'])
            self.msg(channel, message)
        except ValueError:
            logging.warn('invalid incoming message: %s' % message.content.body)


class IRCClientFactory(protocol.ClientFactory):

    def __init__(self, amqp_client):
        self.amqp_client = amqp_client

    def buildProtocol(self, addr):
        self.protocol = IRCClient()
        self.protocol.factory = self
        return self.protocol

    def startedConnecting(self, connector):
        logger.debug("connecting to %s" % connector)

    def clientConnectionLost(self, connector, reason):
        logger.warning("connection lost.")

    def clientConnectFailed(self, connector, reason):
        logger.warning("connection failed: %s" % reason)


def start():
    amqp_client = amqp.AmqpFactory(path.join(CONF.config_dir, "amqp0-8.xml"),
                                   host=CONF.amqp_host,
                                   port=CONF.amqp_port,
                                   user=CONF.amqp_user,
                                   password=CONF.amqp_password)
    irc_client = IRCClientFactory(amqp_client=amqp_client)
    reactor.connectTCP(CONF.irc_host, CONF.irc_port, irc_client)
    reactor.run()
