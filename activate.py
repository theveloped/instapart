#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""A module-level docstring

Notice the comment above the docstring specifying the encoding.
Docstrings do appear in the bytecode, so you can access this through
the ``__doc__`` attribute. This is also what you'll see if you call
help() on a module or any other Python object.
"""

# compatibility imports
from __future__ import print_function

# general imports
import os
import sys
import time
from cryptlex.lexactivator import LexActivator, LexStatusCodes, PermissionFlags, LexActivatorException

import logging
logger = logging.getLogger()

import itertools

if os.name == 'nt':
    try:
        from winreg import *

    except ImportError: # Python 2
        from _winreg import *

def get_user_info(name, path="SOFTWARE\\WOW6432Node\\SmartPart\\UserInfo"):
    logger.info("Checking registry for: {}".format(name))
    value = get_reg(path, name)

    if value:
        logger.info("Found {} in registy: {}".format(name, value))

    return value


def set_reg(path, name, value=""):
    try:
        CreateKey(HKEY_LOCAL_MACHINE, path)
        registry_key = OpenKey(HKEY_LOCAL_MACHINE, path, 0, KEY_WRITE)
        SetValueEx(registry_key, name, 0, REG_SZ, value)
        CloseKey(registry_key)
        return True

    except:
        return False


def get_reg(path, name):
    try:
        registry_key = OpenKey(HKEY_LOCAL_MACHINE, path, 0, KEY_READ)
        value, regtype = QueryValueEx(registry_key, name)
        CloseKey(registry_key)
        return value

    except:
        return None


def licence_callback(status):
    logger.info("License status check: {}".format(status))

    if status != LexStatusCodes.LA_OK:
        sys.exit()


def check_license(meter_attribute=None, meter_increment=1):
    try:
        LexActivator.SetLicenseCallback(licence_callback)
        status = LexActivator.IsLicenseGenuine()
        if LexStatusCodes.LA_OK == status:
            expiryDate = LexActivator.GetLicenseExpiryDate()
            daysLeft = (expiryDate - time.time()) / 86400
            user_name = LexActivator.GetLicenseUserName()

            if meter_attribute and meter_increment:
                try:
                    LexActivator.IncrementActivationMeterAttributeUses(meter_attribute, meter_increment)

                except LexActivatorException as exception:
                    if exception.code != 72:
                        logger.warning("Meter error ({}): {}".format(exception.code, exception.message))

            logger.info("Days left on license: {}".format(daysLeft))
            logger.info("User on license: {}".format(user_name))
            logger.info("License if genuinely activated")

        elif LexStatusCodes.LA_EXPIRED == status:
            logger.warning("License was genuinely activated but has expired")
            main(trail=False, fallback=True)

        elif LexStatusCodes.LA_SUSPENDED == status:
            logger.warning("License was genuinely activated but has been suspended")
            main(trail=False, fallback=True)

        elif LexStatusCodes.LA_GRACE_PERIOD_OVER == status:
            logger.warning("License was genuinely activated but grace period is over")
            main(trail=False, fallback=True)

        else:
            trialStatus = LexActivator.IsTrialGenuine()
            if LexStatusCodes.LA_OK == trialStatus:
                trialExpiryDate = LexActivator.GetTrialExpiryDate()
                daysLeft = (trialExpiryDate - time.time()) / 86400
                logger.info("Days left on trail license: {}".format(daysLeft))

            elif LexStatusCodes.LA_TRIAL_EXPIRED == trialStatus:
                logger.warning("Trail license has expired")
                main(trail=True, fallback=True)
                # sys.exit()

            else:
                logger.warning("Please activate a (trail) license first")
                main(trail=True, fallback=True)
                # sys.exit()

    except LexActivatorException as exception:
        logger.error("License error ({}): {}".format(exception.code, exception.message))
        sys.exit()


def activate(license_key, user_name=None, company_name=None, fallback=False):
    try:
        LexActivator.SetLicenseKey(license_key)

        if user_name:
            LexActivator.SetTrialActivationMetadata("user_name", user_name)

        if company_name:
            LexActivator.SetTrialActivationMetadata("company_name", company_name)

        status = LexActivator.ActivateLicense()
        if LexStatusCodes.LA_OK == status:
            logger.info("License activated: {}".format(status))

        elif LexStatusCodes.LA_EXPIRED == status or LexStatusCodes.LA_SUSPENDED == status:
            logger.warning("License not activated: {}".format(status))

            if fallback:
                logger.info("Trying trial license activation")
                activate_trial(user_name=user_name, company_name=company_name)

            else:
                sys.exit()

        else:
            logger.error("License activation failed: {}".format(status))

            if fallback:
                logger.info("Trying trial license activation")
                activate_trial(user_name=user_name, company_name=company_name)

            else:
                sys.exit()

    except LexActivatorException as exception:
        logger.error("License error ({}): {}".format(exception.code, exception.message))
        sys.exit()


def activate_trial(user_name=None, company_name=None, fallback=False):
    try:
        if user_name:
            LexActivator.SetTrialActivationMetadata("user_name", user_name)

        if company_name:
            LexActivator.SetTrialActivationMetadata("company_name", company_name)

        status = LexActivator.ActivateTrial()
        if LexStatusCodes.LA_OK == status:
            logger.info("Trail license activated: {}".format(status))

        elif LexStatusCodes.LA_TRIAL_EXPIRED == status:
            logger.warning("Trail license expired: {}".format(status))
            license_key = get_user_info("Serial")

            if fallback and license_key:
                logger.info("Trying license activation")
                activate(license_key, user_name=user_name, company_name=company_name)

            else:
                sys.exit()

        else:
            logger.error("Trail license activation failed: {}".format(status))
            license_key = get_user_info("Serial")

            if fallback and license_key:
                logger.info("Trying license activation")
                activate(license_key, user_name=user_name, company_name=company_name)

            else:
                sys.exit()

    except LexActivatorException as exception:
        logger.error("License error ({}): {}".format(exception.code, exception.message))
        sys.exit()


def deactivate():
    try:
        status = LexActivator.DeactivateLicense()

        if LexStatusCodes.LA_OK == status:
            logger.info("License deactivated: {}".format(status))

        else:
            logger.error("License deactivation failed: {}".format(status))

    except LexActivatorException as exception:
        logger.error("License deactivation error ({}): {}".format(exception.code, exception.message))
        sys.exit()



def release_license():
    return
    license_type = LexActivator.GetLicenseType() # node-locked or hosted-floating
    logger.info("Releasing license: {}".format(license_type))

    if license_type == "node-locked":
        logger.info("License is node-locked no need to release license")

    elif license_type == "hosted-floating":
        status = LexActivator.DeactivateLicense()
        if LexStatusCodes.LA_OK == status:
            logger.info("License released: {}".format(status))

        else:
            logger.info("Failed to release license: {}".format(status))

    else:
        logger.warning("License type unknown")


def main(license_key=None, trail=False, user_name=None, company_name=None, fallback=False):
    if not license_key:
        license_key = get_user_info("Serial")

    if not user_name:
        user_name = get_user_info("User")

    if not company_name:
        company_name = get_user_info("Organization")

    if trail or not license_key:
        logger.info("Activating trail license")
        activate_trial(user_name=user_name, company_name=company_name, fallback=fallback)

    else:
        logger.info("Activating license: {}".format(license_key))
        activate(license_key, user_name=user_name, company_name=company_name, fallback=fallback)










