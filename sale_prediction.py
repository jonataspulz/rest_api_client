import os
from datetime import datetime
from typing import Any, Dict, List, Tuple

# Dependencies: scipy, statsmodels
from numpy import zeros
from statsmodels.tsa.vector_ar.var_model import VAR


class VARLessThan2Variables(Exception):
    pass


class Sale:
    def __init__(self, product_option_id: str, sale_date: datetime, quantity: int, group: str):
        self.product_option_id = product_option_id
        self.sale_date = sale_date
        self.quantity = quantity
        self.group = group


class YearMonth:

    def __init__(self, date: datetime):
        self._year = date.year
        self._month = date.month
        self._year_month = int(str(date.year) + str(date.month).zfill(2))

    @property
    def year(self) -> int:
        return self._year

    @property
    def month(self) -> int:
        return self._month

    @property
    def year_month(self) -> int:
        return self._year_month

    def months_diff(self, other):
        if self._year != other.year:
            return (self._year - other.year - 1) * 12 + (12 - other.month) + self._month
        return self._month - other.month

    def add_months(self, n_month):
        years, months = divmod(n_month, 12)
        years_shift, new_month = divmod(self._month + months, 12)
        years_shift += years
        if new_month == 0:
            years_shift -= 1
            new_month = 12
        return YearMonth(datetime(self._year + years_shift, new_month, 1))

    def __eq__(self, other):
        return self._year == other.year and self._month == other.month

    def __lt__(self, other):
        return self._year_month < other.year_month

    def __gt__(self, other):
        return self._year_month > other.year_month

    def __add__(self, other):
        return NotImplemented

    def __sub__(self, other):
        return NotImplemented

    def __str__(self):
        return str(self._year_month)

    def __hash__(self):
        return hash(self._year_month)


class SalePredictor:
    def __init__(self, po_sales: Dict[str, List[Sale]]):
        self._po_sales = po_sales

    def predict_next_month_sales(self, today: datetime):
        # Group the sales to use the product options of the group as endogenous variables of the VAR process
        grouped_sales, group_initial_date = self._group_and_index_sales_by_month()
        data = self._prepare_data(grouped_sales, group_initial_date, YearMonth(today))
        # self._debug_save_group_data(grouped_sales, group_initial_date, data)
        predicted_sales = self._predict(data)
        self._print_predicted_sales(grouped_sales, predicted_sales)

    # noinspection PyMethodMayBeStatic
    def _debug_save_group_data(self, grouped_sales, group_initial_date, data):
        w_dir = os.getcwd() + "\\debug\\"
        ext = ".txt"
        sep = ","
        eol = "\n"
        for group in grouped_sales:
            with open(w_dir + group + ext, "w+", encoding="utf-8") as f:
                for po in grouped_sales[group]:
                    for year_month in grouped_sales[group][po]:
                        f.write(group + sep + po + sep + str(year_month) + sep
                                + str(grouped_sales[group][po][year_month]) + eol)
            with open(w_dir + group + "_series" + ext, "w+", encoding="utf-8") as f:
                f.write("Group" + sep + sep.join(grouped_sales[group]) + eol)
                for i in range(0, len(data[group])):
                    f.write(str(group_initial_date[group].add_months(i)) + sep +
                            sep.join(list(data[group][i].astype(str))) + eol)

    def _group_and_index_sales_by_month(self) -> Tuple[Dict[str, Dict[str, Dict[YearMonth, int]]],
                                                       Dict[str, YearMonth]]:
        # I should use a limit for the past, maybe the last 24 months?
        grouped_sales = {}
        group_initial_year_month = {}
        for po in self._po_sales.keys():
            for sale in self._po_sales[po]:
                # Dict of group of dict of product option of dict of year+month of quantity
                year_month = YearMonth(sale.sale_date)
                grouped_sales.setdefault(sale.group, {}).setdefault(po, {}).\
                    setdefault(year_month, 0)
                grouped_sales[sale.group][po][year_month] += sale.quantity
                # Save the smallest date
                initial_year_month = group_initial_year_month.setdefault(sale.group, year_month)
                if year_month < initial_year_month:
                    group_initial_year_month[sale.group] = year_month
        return grouped_sales, group_initial_year_month

    @staticmethod
    def _prepare_data(grouped_sales: Dict[str, Dict[str, Dict[YearMonth, int]]], group_initial_date,
                      today_year_month: YearMonth):
        data = {}
        for group in grouped_sales:
            group_data = zeros((today_year_month.months_diff(group_initial_date[group]) + 1,
                                len(grouped_sales[group])))
            for po in grouped_sales[group]:
                po_index = list(grouped_sales[group].keys()).index(po)
                for po_year_month in grouped_sales[group][po]:
                    group_data[po_year_month.months_diff(group_initial_date[group])][po_index] = \
                        grouped_sales[group][po][po_year_month]
            data[group] = group_data
        return data

    @staticmethod
    def _predict(data: Dict[str, Any]):
        predicted_sales = {}
        for group in data:
            try:
                # VAR must have at least 2 variables
                if len(data[group][0]) < 2:
                    raise VARLessThan2Variables
                sales_model = VAR(data[group])
                sales_model_fit = sales_model.fit()
                predicted_sales[group] = sales_model_fit.forecast(sales_model_fit.y, steps=1)
            except (ValueError, VARLessThan2Variables):
                predicted_sales[group] = None
        return predicted_sales

    @staticmethod
    def _print_predicted_sales(grouped_sales, predicted_sales):
        for group in grouped_sales:
            if predicted_sales[group] is None:
                continue
            print(group + "---------------------")
            for po in grouped_sales[group]:
                i = list(grouped_sales[group]).index(po)
                print(po + ": " + str(round(predicted_sales[group][0][i])))
            print("---------------------")
