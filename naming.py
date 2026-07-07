import re
import random
import string

import logging
logger = logging.getLogger()

def generate_name(file_name, part, used_names, source="PART", delimiter="_", trim_side="START", pad_side="END", charset=r'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-', min_length=None, max_length=None, prefix=None, postfix=None):
    logger.debug("[+] generating name, filename: {}, partname: {}".format(file_name, part.name))
    logger.debug(" -  min: {}, max: {}, trim: {}".format(min_length, max_length, trim_side))

    if source == "PART":
        option = shorten_string(part.name, delimiter=delimiter, trim_side=trim_side, pad_side=pad_side, charset=charset, min_length=min_length, max_length=max_length)

    else:
        option = shorten_string(file_name, delimiter=delimiter, trim_side=trim_side, pad_side=pad_side, charset=charset, min_length=min_length, max_length=max_length)

    index = 0
    original_option = option
    while option in used_names:
        index += 1
        index_string = "{}{}".format(delimiter, index)
        index_length = len(index_string)

        # Reste option
        option = original_option

        # Only trim if needed
        if max_length:
            if len(original_option) + index_length > max_length:
                option = original_option[:max_length - index_length]

        # Add index
        option += index_string

    original_option = option

    if prefix:
        variables = re.findall(r'\{\{(\w+?)\}\}', prefix)

        for variable in variables:

            if variable.lower() == "count":
                prefix = re.sub("{{count}}", "{}".format(part.count), prefix)

        option = "{}{}".format(prefix, option)

    if postfix:
        variables = re.findall(r'\{\{(\w+?)\}\}', postfix)

        for variable in variables:

            if variable.lower() == "count":
                postfix = re.sub("{{count}}", "{}".format(part.count), postfix)

        option = "{}{}".format(option, postfix)


    return original_option, option



def shorten_string(value, delimiter="_", trim_side="START", pad_side="END", charset=r'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-', min_length=None, max_length=None):
    blacklist = r"[^{}]".format(charset)
    length = len(value)
    result = value

    logger.debug("+ {: <30} {: <30} {: <10}".format("Step:", "Value:", "Length:"))
    logger.debug("- {: <30} {: <30} {: <10}".format("original", result, len(result)))

    result = strip_string(result, delimiter=delimiter)
    logger.debug("- {: <30} {: <30} {: <10}".format("strip", result, len(result)))

    if charset:
        result = blacklist_string(result, delimiter=delimiter, strip=True)
        logger.debug("- {: <30} {: <30} {: <10}".format("blacklist", result, len(result)))

    if max_length:
        result = trim_string(result, max_length, side=trim_side, strip=True)
        logger.debug("- {: <30} {: <30} {: <10}".format("trim", result, len(result)))

    if min_length:
        result = pad_string(result, min_length, side=pad_side, delimiter="")
        logger.debug("- {: <30} {: <30} {: <10}".format("pad", result, len(result)))

    return result


def random_string(length=10):
    """Generate a random string of fixed length """
    letters = string.ascii_lowercase
    return ''.join(random.choice(letters) for i in range(length))



def blacklist_string(value, blacklist=r'[^a-zA-Z0-9_-]', delimiter="", strip=True):
    value = re.sub(blacklist, '', value)

    if strip:
        value = strip_string(value)

    return value


def strip_string(value, delimiter="_"):
    value = value.strip()

    return re.sub(r'[\s\_]+', delimiter, value)


def trim_string(value, length, side="START", strip=True):
    trim_length = len(value) - length

    if trim_length > 0:

        if side.lower() == "start":
            value = value[trim_length:]

        elif side.lower() == "end":
            value = value[:-trim_length]

    if strip:
        value = strip_string(value)

    return value


def pad_string(value, length, side="START", delimiter="", padding="0"):
    trim_length = len(value) - length

    if trim_length < 0:

        if side.lower() == "start":
            value = "{}{}{}".format(padding * abs(trim_length), delimiter, value)

        elif side.lower() == "end":
            value = "{}{}{}".format(value, delimiter, padding * abs(trim_length))

    return value


def shorten_strings(values, length=10, blacklist=r'[^a-zA-Z0-9_-]'):
    lengths = []
    results = []

    logger.debug("+ {: <30} {: <30} {: <10} {: <10}".format("Step:", "Value:", "Length:", "Diff:"))
    for value in values:
        value_length = len(value)
        lengths.append(value_length)
        results.append(value)

        logger.debug("- {: <30} {: <30} {: <10} {: <10}".format("original", value, value_length, value_length-length))


    logger.debug("")
    for i in range(len(values)):
        results[i] = strip_string(results[i])
        value_length = len(results[i])

        logger.debug("- {: <30} {: <30} {: <10} {: <10}".format("strip", results[i], value_length, value_length-length))


    logger.debug("")
    for i in range(len(values)):
        results[i] = blacklist_string(results[i], strip=True)
        value_length = len(results[i])

        logger.debug("- {: <30} {: <30} {: <10} {: <10}".format("blacklist", results[i], value_length, value_length-length))


    logger.debug("")
    for test in range(100):
        maximum = 0
        maximum_index = -1
        for i in range(len(values)):
            value_length = len(results[i])

            if value_length - length > maximum:
                maximum = value_length
                maximum_index = i

        # logger.debug(maximum_index, results[maximum_index], maximum)

        if maximum_index == -1:
            break

        savings = []
        for j in range(maximum):
            savings.append(0)

            for i in range(len(values)):
                saving = j + 1

                if i == maximum_index:
                    continue

                if results[i][:saving] == results[maximum_index][:saving]:
                    saving = min(abs(len(results[i]) - length), saving)


                    # logger.debug("---", saving)
                    savings[-1] += saving

            # logger.debug("saving", results[maximum_index][:j + 1], savings[-1])

        if len(savings) > 0:
            maximum_saving = max(savings)

            for j in range(len(savings)):
                if savings[j] == maximum_saving:

                    # logger.debug("stripping", results[maximum_index][:j + 1])
                    pattern = results[maximum_index][:j + 1]

                    for i in range(len(values)):
                        saving = min(len(results[i]) - length, (j + 1))
                        # saving =
                        # logger.debug(saving)

                        if results[i][:saving] == pattern[:saving]:
                            results[i] = results[i][saving:]

                        value_length = len(results[i])
                        # logger.debug("- {: <30} {: <30} {: <10} {: <10}".format("smart", results[i], value_length, value_length-length))

                    break

    for result in results:
        value_length = len(result)
        logger.debug("- {: <30} {: <30} {: <10} {: <10}".format("smart", result, value_length, value_length-length))


if __name__ == "__main__":
    values = [
        "hoi_dit is een sting_1",
        "hoi_dit is  een sting_2",
        "hoi_2-",
        "hoi_2-",
        "hoi_dit @# is sting2",
        "tubePart23$part",
        "tubePart24$part",
        "hoi_dit is"
    ]

    for value in values:
        shorten_string(value, trim_side="end", min_length=10, max_length=10)
