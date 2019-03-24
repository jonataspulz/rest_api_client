from datetime import datetime
from numpy import zeros
from typing import Any, Dict, List, Tuple

# Dependencies: scipy, statsmodels
from statsmodels.tsa.vector_ar.var_model import VAR


class Sale:
    def __init__(self, product_option_id: str, sale_date: datetime, quantity: int, group: str):
        self.product_option_id = product_option_id
        self.sale_date = sale_date
        self.quantity = quantity
        self.group = group


class SalePredictor:
    def __init__(self, po_sales: Dict[str, List[Sale]]):
        self._po_sales = po_sales

    def predict_next_month_sales(self, today: datetime):
        # Group the sales to use the product options of the group as endogenous variables of the VAR process
        grouped_sales, group_initial_date = self._group_and_index_sales_by_month()
        data = self._prepare_data(grouped_sales, group_initial_date, int(str(today.year) + str(today.month).zfill(2)))
        self._predict(data)

    def _group_and_index_sales_by_month(self) -> Tuple[Dict[str, Dict[str, Dict[int, int]]], Dict[str, int]]:
        # I should use a limit for the past, maybe the last 24 months?
        grouped_sales = {}
        group_initial_year_month = {}
        for po in self._po_sales.keys():
            for sale in self._po_sales[po]:
                # Dict of group of dict of product option of dict of year+month of quantity
                year_month = int(str(sale.sale_date.year) + str(sale.sale_date.month).zfill(2))
                year_month_quantity = grouped_sales.setdefault(sale.group, {}).setdefault(po, {}).\
                    setdefault(year_month, sale.quantity)
                if year_month_quantity:
                    grouped_sales[sale.group][po][year_month] += sale.quantity
                # Save the smallest date
                initial_year_month = group_initial_year_month.setdefault(sale.group, year_month)
                if initial_year_month:
                    if year_month < initial_year_month:
                        group_initial_year_month[sale.group] = year_month
        return grouped_sales, group_initial_year_month

    # noinspection PyMethodMayBeStatic
    def _prepare_data(self, grouped_sales: Dict[str, Dict[str, Dict[int, int]]], group_initial_date, today_year_month):
        data = {}
        for group in grouped_sales:
            group_data = zeros((today_year_month - group_initial_date[group] + 1, len(grouped_sales[group])))
            for po in grouped_sales[group]:
                po_index = list(grouped_sales[group].keys()).index(po)
                for po_year_month in grouped_sales[group][po]:
                    group_data[po_year_month - group_initial_date[group]][po_index] = \
                        grouped_sales[group][po][po_year_month]
            data[group] = group_data
        return data

    # noinspection PyMethodMayBeStatic
    def _predict(self, data: Dict[str, Any]):
        for group_data in data.values():
            # VAR must have at least 2 variables
            if len(group_data[0]) < 2:
                continue
            sales_model = VAR(group_data)
            sales_model_fit = sales_model.fit()
            predicted_sales = sales_model_fit.forecast(sales_model_fit.y, steps=1)
            print(predicted_sales)
