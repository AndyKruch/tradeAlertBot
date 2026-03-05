import pandas as pd


def _read_file(filename):
    from os.path import dirname, join

    return pd.read_csv(join(dirname(__file__), filename), index_col=0, parse_dates=True)


SBER = _read_file('BBG004730N88.csv')
IMOEXF = _read_file('FUTIMOEXF000.csv')