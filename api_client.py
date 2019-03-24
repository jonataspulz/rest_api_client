
import json
import sys
import traceback
from datetime import datetime
from enum import Enum, unique
from typing import Any, Dict, List, Optional, Tuple
from urllib.error import URLError
from urllib.parse import urlunparse
from urllib.request import Request, urlopen

from sale_prediction import Sale, SalePredictor


def to_datetime(iso_datetime: str) -> datetime:
    return datetime.strptime(iso_datetime, "%Y%m%dT%H%M%S.000Z")


class _FaireRequest:
    _API_KEY_HEADER = "X-FAIRE-ACCESS-TOKEN"
    _URL_SCHEME = "http"
    _URL_NETLOC = "www.faire-stage.com"
    _URL_API_PREFIX = "/api/v1"
    _LIMIT_QUERY_KEY = "limit"
    _PAGE_QUERY_KEY = "page"

    def __init__(self, api_key: str):
        self._api_key = api_key

    def get_all_items_from_path(self, path, item_type) -> List:
        limit = 50
        page = 1
        items = []
        next_page = self._get_http_request(path, {self._LIMIT_QUERY_KEY: limit, self._PAGE_QUERY_KEY: page})
        try:
            items.extend(next_page[item_type])
        except KeyError as ex:
            print("Wrong item type {} for path {}".format(path, item_type))
            raise ex
        while len(next_page[item_type]) >= limit:
            page += 1
            next_page = self._get_http_request(path, {self._LIMIT_QUERY_KEY: limit, self._PAGE_QUERY_KEY: page})
            items.extend(next_page[item_type])
        return items

    def post_http_request(self, path: str, data: str) -> Dict:
        return self._http_request(path, None, data, "POST")

    def patch_http_request(self, path: str, data: str) -> Dict:
        return self._http_request(path, None, data, "PATCH")

    def put_http_request(self, path: str) -> Dict:
        return self._http_request(path, None, "{}", "PUT")

    def _get_http_request(self, path: str, query_params: Dict) -> Dict:
        return self._http_request(path, query_params)

    def _http_request(self, path, query_params: Optional[Dict], data: str = None, method: str = None) -> Dict:
        url = self._build_url_from_path_query(path, query_params)
        http_resp = self._open_url(url, data, method)
        return json.loads(http_resp.read().decode("utf-8"))

    def _build_url_from_path_query(self, path: str, query_params: Dict = None) -> str:
        if query_params:
            query = "&".join([str(key) + "=" + str(value) for key, value in query_params.items()])
        else:
            query = ""
        url_comps = (self._URL_SCHEME, self._URL_NETLOC, self._URL_API_PREFIX + path, "", query, "")
        return urlunparse(url_comps)

    def _open_url(self, url: str, data: str = None, method: str = None):
        try:
            http_resp = urlopen(self._build_request(url, data, method))
        except URLError as ex:
            print("Protocol error. URL {}".format(url))
            raise ex
        return http_resp

    def _build_request(self, url: str, data: str = None, method: str = "GET") -> Request:
        return Request(url, (lambda d: bytes(d, "utf-8") if d is not None else None)(data),
                       {self._API_KEY_HEADER: self._api_key, "Content-Type": "application/json;charset=utf-8"},
                       method=method)


class _FaireObj:
    ITEM_TYPE = ""
    URL_PATH = ""

    def __init__(self, parsed_obj):
        self.id = parsed_obj["id"]


class _GettableFaireObj(_FaireObj):

    @classmethod
    def get_all_items(cls, request: _FaireRequest) -> List:
        return request.get_all_items_from_path(cls.get_obj_path(), cls.ITEM_TYPE)

    @classmethod
    def get_obj_path(cls) -> str:
        return ""

    def get_obj_uri(self) -> str:
        return self.get_obj_path() + "/" + str(self.id)


class Product(_GettableFaireObj):
    ITEM_TYPE = "products"
    URL_PATH = "/products"

    def __init__(self, parsed_obj: Dict):
        super().__init__(parsed_obj)
        self.brand_id = parsed_obj["brand_id"]
        try:
            self.short_description = parsed_obj["short_description"]
        except KeyError:
            self.short_description = None
        try:
            self.description = parsed_obj["description"]
        except KeyError:
            self.description = None
        self.wholesale_price_cents = parsed_obj["wholesale_price_cents"]
        self.retail_price_cents = parsed_obj["retail_price_cents"]
        self.active = parsed_obj["active"]
        self.name = parsed_obj["name"]
        self.unit_multiplier = parsed_obj["unit_multiplier"]
        self.options_dict = {po.id: po for po in [ProductOption(it) for it in parsed_obj["options"]]}
        self.created_at = parsed_obj["created_at"]
        self.updated_at = parsed_obj["updated_at"]

    @classmethod
    def get_obj_path(cls) -> str:
        return cls.URL_PATH


class ProductOption(Product):
    ITEM_TYPE = "options"
    URL_PATH = "/products/options"

    def __init__(self, parsed_obj: Dict):
        _FaireObj.__init__(self, parsed_obj)
        self.product_id = parsed_obj["product_id"]
        self.active = parsed_obj["active"]
        self.name = parsed_obj["name"]
        try:
            self.sku = parsed_obj["sku"]
        except KeyError:
            self.sku = None
        try:
            self._available_quantity = parsed_obj["available_quantity"]
        except KeyError:
            self._available_quantity = None
        try:
            self.backordered_until = parsed_obj["backordered_until"]
        except KeyError:
            self.backordered_until = None
        self.created_at = parsed_obj["created_at"]
        self.updated_at = parsed_obj["updated_at"]

    @classmethod
    def get_obj_path(cls) -> str:
        return cls.URL_PATH

    @property
    def available_quantity(self) -> int:
        if self._available_quantity is None:
            return 0
        else:
            return self._available_quantity

    @available_quantity.setter
    def available_quantity(self, available_quantity: int):
        self._available_quantity = available_quantity

    def update_product_option(self, request: _FaireRequest, new_quantity: int):
        # TODO implement exception handling
        if new_quantity < 0:
            print("Invalid production option new quantity: {}".format(new_quantity))
            raise Exception
        json_patch = {"op": "replace", "path": "/available_units", "value": new_quantity}
        request.patch_http_request(self.get_obj_uri(), json.dumps(json_patch))
        self._available_quantity = new_quantity


class OrderItem(_FaireObj):

    def __init__(self, parsed_obj: Dict):
        super().__init__(parsed_obj)
        self.order_id = parsed_obj["order_id"]
        self.product_id = parsed_obj["product_id"]
        self.product_option_id = parsed_obj["product_option_id"]
        self.quantity = parsed_obj["quantity"]
        self.sku = parsed_obj["sku"]
        self.price_cents = parsed_obj["price_cents"]
        self.product_name = parsed_obj["product_name"]
        self.product_option_name = parsed_obj["product_option_name"]
        self.includes_tester = parsed_obj["includes_tester"]
        try:
            self.tester_price_cents = parsed_obj["tester_price_cents"]
        except KeyError:
            self.tester_price_cents = None
        self.created_at = parsed_obj["created_at"]
        self.updated_at = parsed_obj["updated_at"]

    def calculate_order_item_dollar_amount(self) -> float:
        # Should I include the tester price?
        return self.quantity * self.price_cents/100.0


class Order(_GettableFaireObj):
    ITEM_TYPE = "orders"
    URL_PATH = "/orders"

    @unique
    class _OrderState(Enum):
        NEW = "NEW"
        PROCESSING = "PROCESSING"
        PRE_TRANSIT = "PRE_TRANSIT"
        IN_TRANSIT = "IN_TRANSIT"
        DELIVERED = "DELIVERED"
        BACKORDERED = "BACKORDERED"
        CANCELED = "CANCELED"

    SOLD_STATES = {_OrderState.PROCESSING.value,
                   _OrderState.PRE_TRANSIT.value,
                   _OrderState.IN_TRANSIT.value,
                   _OrderState.DELIVERED.value}

    def __init__(self, parsed_obj: Dict):
        super().__init__(parsed_obj)
        self.state = parsed_obj["state"]
        self.ship_after = parsed_obj["ship_after"]
        self.items_dict: Dict[str, OrderItem] = {oi.id: oi for oi in [OrderItem(it) for it in parsed_obj["items"]]}
        self.shipments = parsed_obj["shipments"]
        self.address = Address(parsed_obj["address"])
        self.created_at = parsed_obj["created_at"]
        self.updated_at = parsed_obj["updated_at"]

    @classmethod
    def get_obj_path(cls) -> str:
        return cls.URL_PATH

    @property
    def date_time(self) -> datetime:
        return to_datetime(self.created_at)

    def is_new(self) -> bool:
        return self.state == self._OrderState.NEW.value

    def is_sold(self) -> bool:
        return self.state in self.SOLD_STATES

    def is_canceled(self) -> bool:
        return self.state == self._OrderState.CANCELED.value

    def accept_order(self, request: _FaireRequest):
        request.put_http_request(self.get_obj_uri() + "/processing")
        self.state = self._OrderState.PROCESSING.value

    def backorder_items(self, items_to_backorder: Dict[OrderItem, ProductOption], request):
        post_dict = {}
        for order_item in items_to_backorder.keys():
            post_dict[order_item.id] = {"available_quantity": items_to_backorder[order_item].available_quantity,
                                        "discontinued": False}
        request.post_http_request(self.get_obj_uri() + "/items/availability", json.dumps(post_dict))
        self.state = self._OrderState.BACKORDERED.value

    def calculate_order_dollar_amount(self) -> float:
        dollar_amount = 0
        for order_item in self.items_dict.values():
            dollar_amount += order_item.calculate_order_item_dollar_amount()
        return dollar_amount

    def calculate_items_quantity(self) -> int:
        quantity = 0
        for order_item in self.items_dict.values():
            quantity += order_item.quantity
        return quantity


class Address:

    def __init__(self, parsed_address: Dict):
        try:
            self.name = parsed_address["name"]
        except KeyError:
            self.name = None
        self.address1 = parsed_address["address1"]
        try:
            self.address2 = parsed_address["address2"]
        except KeyError:
            self.address2 = None
        self.postal_code = parsed_address["postal_code"]
        self.city = parsed_address["city"]
        self.state = parsed_address["state"]
        self.state_code = parsed_address["state_code"]
        try:
            self.phone_number = parsed_address["phone_number"]
        except KeyError:
            self.phone_number = None
        self.country = parsed_address["country"]
        self.country_code = parsed_address["country_code"]
        self.company_name = parsed_address["company_name"]


class InventoryLevelsUpdater(_FaireObj):
    URL_PATH = "/products/options/inventory-levels"
    INVENTORY_KEY = "inventories"

    @classmethod
    def update_inventory_levels(cls, product_options_levels: Dict[ProductOption, int],
                                request: _FaireRequest):
        inventory = {cls.INVENTORY_KEY: []}
        for product_option in product_options_levels.keys():
            if product_option.sku is None:
                continue
            current_quantity = product_options_levels[product_option]
            product_opt_inventory = {"sku": product_option.sku,
                                     "current_quantity": current_quantity,
                                     "discontinued": False}
            inventory[cls.INVENTORY_KEY].append(product_opt_inventory)
        request.patch_http_request(cls.URL_PATH, json.dumps(inventory))


class OrderProcessor:

    def __init__(self, api_key: str, brand: str):
        self._request = _FaireRequest(api_key)

        self.brand = brand
        products = self._consume_item(Product.ITEM_TYPE)
        if self.brand is not None:
            products = list(filter(lambda product: product.brand_id == self.brand, products))
        self.products_dict: Dict[str, Product] = {product.id: product for product in products}
        self.orders: List[Order] = self._consume_item(Order.ITEM_TYPE)

    def process_orders(self):
        # self._test_update_inventory()
        for order in self._filter_and_sort_orders_by_creation():
            self._update_order_status_and_product_inventory(order)

    def print_metrics(self):
        self._calculate_and_print_metrics()

    def get_products_sale_series(self) -> Dict[str, List[Sale]]:
        po_sales = {}
        for order in self.orders:
            for order_item in order.items_dict.values():
                po_sales.setdefault(order_item.product_option_id, []).\
                    append(Sale(order_item.product_option_id, order.date_time,
                                order_item.quantity, order.address.state))
        return po_sales

    def _test_update_inventory(self):
        po_quantity_to_update = {}
        for product in self.products_dict.values():
            for product_option in product.options_dict.values():
                po_quantity_to_update[product_option] = 300
        self._update_inventory_levels(po_quantity_to_update)

    def _consume_item(self, item_type: str) -> List[_GettableFaireObj]:
        if item_type == Product.ITEM_TYPE:
            return [Product(item) for item in Product.get_all_items(self._request)]
        if item_type == Order.ITEM_TYPE:
            return [Order(item) for item in Order.get_all_items(self._request)]
        # TODO implement exception handling
        print("Not known item type {}".format(item_type))
        raise Exception

    def _filter_and_sort_orders_by_creation(self) -> List[Order]:
        orders_to_process = list(filter(lambda order: order.is_new(), self.orders))
        orders_to_process = sorted(orders_to_process, key=lambda order: order.created_at)
        return list(orders_to_process)

    def _update_order_status_and_product_inventory(self, order: Order):
        items_to_backorder = {}
        po_quantity_to_update = {}
        for order_item in order.items_dict.values():
            try:
                product_option = self.products_dict[order_item.product_id].options_dict[order_item.product_option_id]
            except KeyError:
                # TODO implement exception handling
                print("Is order {} from brand {}?".format(order.id, self.brand))
                continue
            if product_option.available_quantity < order_item.quantity:
                items_to_backorder[order_item] = product_option
            else:
                po_quantity_to_update[product_option] = product_option.available_quantity - order_item.quantity
        if not items_to_backorder:
            self._update_inventory_levels(po_quantity_to_update)
            order.accept_order(self._request)
        else:
            order.backorder_items(items_to_backorder, self._request)

    def _update_inventory_levels(self, po_quantity_to_update: Dict[ProductOption, int]):
        # Looks like the PATCH for Product Option in the API is not working
        # for product_option in po_quantity_to_update.keys():
            # product_option.update_product_option(self._request, po_quantity_to_update[product_option])
        # I'll use Update Inventory Levels instead
        InventoryLevelsUpdater.update_inventory_levels(po_quantity_to_update, self._request)

    def _calculate_and_print_metrics(self):
        self._print_best_selling_product_option()
        self._print_largest_order_dollar_amount()
        self._print_state_with_most_orders()
        self._print_biggest_order_by_quantity()
        self._print_ratio_of_cancelled_orders()

    def _print_best_selling_product_option(self):
        products_options_sell_info = {}
        for order in list(filter(lambda o: o.is_sold(), self.orders)):
            for order_item in order.items_dict.values():
                product_option = self.products_dict[order_item.product_id].options_dict[order_item.product_option_id]
                count = products_options_sell_info.setdefault(product_option, 0)
                products_options_sell_info[product_option] = count + order_item.quantity
        best_selling, number = self._sort_and_get_first(products_options_sell_info, True)
        if best_selling is None:
            print("No products sold yet")
        else:
            print("Best selling product has id \"{}\" and name \"{}\". Sold {} units".format(
                best_selling.id, (lambda n: n if n is not None else "")(best_selling.name), number))

    def _print_largest_order_dollar_amount(self):
        # I think that only sold orders should be taken into account
        orders_dollar_amount = {}
        for order in list(filter(lambda o: o.is_sold(), self.orders)):
            orders_dollar_amount[order] = order.calculate_order_dollar_amount()
        largest_order, dollar_amount = self._sort_and_get_first(orders_dollar_amount, True)
        if largest_order is None:
            print("No orders sold yet")
        else:
            print("Largest order dollar amount has id \"{}\". Value is {} dollars".format(largest_order.id,
                                                                                          dollar_amount))

    def _print_state_with_most_orders(self):
        # I think that only sold orders should be taken into account
        state_order_count = {}
        for order in list(filter(lambda o: o.is_sold(), self.orders)):
            count = state_order_count.setdefault(order.address.state, 0)
            state_order_count[order.address.state] = count + 1
        state_with_most, state_count = self._sort_and_get_first(state_order_count, True)
        if state_with_most is None:
            print("No orders sold yet")
        else:
            print("State with most orders is  \"{}\". It has {} orders".format(state_with_most, state_count))

    def _print_biggest_order_by_quantity(self):
        # I think that only sold orders should be taken into account
        order_item_quantity = {}
        for order in list(filter(lambda o: o.is_sold(), self.orders)):
            order_item_quantity[order] = order.calculate_items_quantity()
        biggest_order, quantity = self._sort_and_get_first(order_item_quantity, True)
        if biggest_order is None:
            print("No orders sold yet")
        else:
            print("Largest order by items quantity has id \"{}\". Quantity is {} units".format(biggest_order.id,
                                                                                               quantity))

    def _print_ratio_of_cancelled_orders(self):
        total_orders = len(self.orders)
        canceled_orders = len(list(filter(lambda o: o.is_canceled(), self.orders)))
        if total_orders == 0:
            print("No orders found")
        else:
            print("Total number of orders is {}. Canceled orders number is {}. The ratio is {}".format(
                total_orders, canceled_orders, canceled_orders/total_orders * 1.0))

    # noinspection PyMethodMayBeStatic
    def _sort_and_get_first(self, obj_dict: Dict[Any, Any], reverse=False) -> Tuple[Optional[Any], Any]:
        if not obj_dict:
            return None, None
        else:
            objs = list(obj_dict.keys())
            counts = list(obj_dict.values())
            idx = sorted(range(0, len(objs)), key=counts.__getitem__, reverse=reverse)[0]
            return objs[idx], counts[idx]


if __name__ == "__main__":
    try:
        http_key = sys.argv[1]
    except IndexError:
        # noinspection SpellCheckingInspection
        http_key = \
            "HQLA9307HSLQYTC24PO2G0LITTIOHS2MJC8120PVZ83HJK4KACRZJL91QB7K01NWS2TUCFXGCHQ8HVED8WNZG0KS6XRNBFRNGY71"
    try:
        brand_token = sys.argv[2]
    except IndexError:
        brand_token = "b_d2481b88"
    # noinspection PyBroadException
    try:
        order_processor = OrderProcessor(http_key, brand_token)
        order_processor.process_orders()
        order_processor.print_metrics()
        foreseen_sales = SalePredictor(order_processor.get_products_sale_series())\
            .predict_next_month_sales(datetime.today())
        pass
    except Exception:
        print(traceback.format_exc())
