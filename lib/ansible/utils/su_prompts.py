# -*- coding: utf-8 -*-

# (c) 2012-2014, Michael DeHaan <michael.dehaan@gmail.com>
#
# This file is part of Ansible
#
# Ansible is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Ansible is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Ansible.  If not, see <http://www.gnu.org/licenses/>.

import re

SU_PROMPT_LOCALIZATIONS = [
    re.compile('Password ?: ?', flags=re.IGNORECASE),
    re.compile('암호 ?: ?', flags=re.IGNORECASE),
    re.compile('パスワード ?: ?', flags=re.IGNORECASE),
    re.compile('Adgangskode ?: ? ', flags=re.IGNORECASE),
    re.compile('Contraseña ?: ?', flags=re.IGNORECASE),
    re.compile('Contrasenya ?: ?', flags=re.IGNORECASE),
    re.compile('Hasło ?: ?', flags=re.IGNORECASE),
    re.compile('Heslo ?: ?', flags=re.IGNORECASE),
    re.compile('Jelszó ?: ?', flags=re.IGNORECASE),
    re.compile('Lösenord ?: ?', flags=re.IGNORECASE),
    re.compile('Mật khẩu ?: ?', flags=re.IGNORECASE),
    re.compile('Mot de passe ?: ?', flags=re.IGNORECASE),
    re.compile('Parola ?: ?', flags=re.IGNORECASE),
    re.compile('Parool ?: ?', flags=re.IGNORECASE),
    re.compile('Pasahitza ?: ?', flags=re.IGNORECASE),
    re.compile('Passord ?: ?', flags=re.IGNORECASE),
    re.compile('Passwort ?: ?', flags=re.IGNORECASE),
    re.compile('Salasana ?: ?', flags=re.IGNORECASE),
    re.compile('Sandi ?: ?', flags=re.IGNORECASE),
    re.compile('Senha ?: ?', flags=re.IGNORECASE),
    re.compile('Wachtwoord ?: ?', flags=re.IGNORECASE),
    re.compile('ססמה ?: ?', flags=re.IGNORECASE),
    re.compile('Лозинка ?: ?', flags=re.IGNORECASE),
    re.compile('Парола ?: ?', flags=re.IGNORECASE),
    re.compile('Пароль ?: ?', flags=re.IGNORECASE),
    re.compile('गुप्तशब्द ?: ?', flags=re.IGNORECASE),
    re.compile('शब्दकूट ?: ?', flags=re.IGNORECASE),
    re.compile('సంకేతపదము ?: ? ', flags=re.IGNORECASE),
    re.compile('රහස්පදය ?: ?', flags=re.IGNORECASE),
    re.compile('密码：', flags=re.IGNORECASE),
    re.compile('密碼：', flags=re.IGNORECASE),
]

def check_su_prompt(data):
    '''
    Attempts to match the given data to one of the su localization
    regexes contained in the above array
    '''
    for prompt in SU_PROMPT_LOCALIZATIONS:
        if prompt.match(data):
            return True
    return False
