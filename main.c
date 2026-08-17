/*
  ESP-IDF — WiFi <-> UART Bridge to Arduino Mega (main/main.c)
  ---------------------------------------------------------------------
  ROLE: pure passthrough, nothing else. Python connects to this ESP32
  over WiFi (plain TCP socket, port 8888); every line Python sends gets
  forwarded to the Mega over UART, and every line the Mega sends back
  gets forwarded back to Python over the same TCP connection. No
  parsing, no decisions, no pump logic here — all of that lives in
  Python (irrigation.py, navigation.py, etc). This is the ESP-IDF
  equivalent of esp32_bridge.ino (Arduino framework) — pick whichever
  toolchain you prefer, they do the same job.

  WIRING (Mega Serial2):
      ESP32 GPIO16 (RX2) <- Mega TX2 (pin 16)
      ESP32 GPIO17 (TX2) -> Mega RX2 (pin 17)
      GND <-> GND

  PYTHON SIDE: set config.CONNECTION_MODE = "wifi" and point
  config.ESP32_BRIDGE_IP at whatever this prints on boot (also visible
  via `idf.py monitor`). See wifi_manager.py in farm_rover_python/.

  Build:
      idf.py create-project esp32_bridge
      -> drop this file in as main/main.c
      idf.py menuconfig   -> not required, defaults are fine
      idf.py set-target esp32
      idf.py build flash monitor
*/
#include <string.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/event_groups.h"
#include "esp_wifi.h"
#include "esp_event.h"
#include "esp_log.h"
#include "nvs_flash.h"
#include "driver/uart.h"
#include "lwip/sockets.h"
#include "lwip/netdb.h"

// ---- WiFi ----
#define WIFI_SSID       "Oneplus 15"
#define WIFI_PASS       "12345678"
#define WIFI_MAXIMUM_RETRY 1000

// ---- TCP bridge port (Python connects here) ----
#define BRIDGE_PORT     8888

// ---- UART to Mega ----
#define UART_PORT       UART_NUM_2
#define UART_RX_PIN     16
#define UART_TX_PIN     17
#define UART_BAUD       9600
#define BUF_SIZE        512

static const char *TAG = "ESP32_BRIDGE";

static EventGroupHandle_t s_wifi_event_group;
#define WIFI_CONNECTED_BIT BIT0
#define WIFI_FAIL_BIT      BIT1
static int s_retry_num = 0;

// shared client socket, written by the accept task, read by the UART->socket task.
// simple bridge, single client at a time — a mutex would be overkill here.
static volatile int s_client_sock = -1;

// ---------------- WiFi station setup ----------------

static void wifi_event_handler(void *arg, esp_event_base_t event_base,
                                int32_t event_id, void *event_data) {
    if (event_base == WIFI_EVENT && event_id == WIFI_EVENT_STA_START) {
        esp_wifi_connect();
    } else if (event_base == WIFI_EVENT && event_id == WIFI_EVENT_STA_DISCONNECTED) {
        if (s_retry_num < WIFI_MAXIMUM_RETRY) {
            esp_wifi_connect();
            s_retry_num++;
            ESP_LOGI(TAG, "retrying WiFi connection (%d/%d)", s_retry_num, WIFI_MAXIMUM_RETRY);
        } else {
            xEventGroupSetBits(s_wifi_event_group, WIFI_FAIL_BIT);
        }
    } else if (event_base == IP_EVENT && event_id == IP_EVENT_STA_GOT_IP) {
        ip_event_got_ip_t *event = (ip_event_got_ip_t *) event_data;
        ESP_LOGI(TAG, "Bridge ready at: " IPSTR ":%d", IP2STR(&event->ip_info.ip), BRIDGE_PORT);
        s_retry_num = 0;
        xEventGroupSetBits(s_wifi_event_group, WIFI_CONNECTED_BIT);
    }
}

static void wifi_init_sta(void) {
    s_wifi_event_group = xEventGroupCreate();

    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    esp_netif_create_default_wifi_sta();

    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&cfg));

    esp_event_handler_instance_t instance_any_id, instance_got_ip;
    ESP_ERROR_CHECK(esp_event_handler_instance_register(
        WIFI_EVENT, ESP_EVENT_ANY_ID, &wifi_event_handler, NULL, &instance_any_id));
    ESP_ERROR_CHECK(esp_event_handler_instance_register(
        IP_EVENT, IP_EVENT_STA_GOT_IP, &wifi_event_handler, NULL, &instance_got_ip));

    wifi_config_t wifi_config = {
        .sta = {
            .ssid = WIFI_SSID,
            .password = WIFI_PASS,
        },
    };
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &wifi_config));
    ESP_ERROR_CHECK(esp_wifi_start());

    ESP_LOGI(TAG, "Connecting to WiFi SSID:%s", WIFI_SSID);
    EventBits_t bits = xEventGroupWaitBits(s_wifi_event_group,
        WIFI_CONNECTED_BIT | WIFI_FAIL_BIT, pdFALSE, pdFALSE, portMAX_DELAY);

    if (bits & WIFI_CONNECTED_BIT) {
        ESP_LOGI(TAG, "WiFi connected.");
    } else {
        ESP_LOGE(TAG, "WiFi connect failed after %d retries.", WIFI_MAXIMUM_RETRY);
    }
}

// ---------------- UART setup ----------------

static void uart_init(void) {
    uart_config_t cfg = {
        .baud_rate = UART_BAUD,
        .data_bits = UART_DATA_8_BITS,
        .parity    = UART_PARITY_DISABLE,
        .stop_bits = UART_STOP_BITS_1,
        .flow_ctrl = UART_HW_FLOWCTRL_DISABLE,
        .source_clk = UART_SCLK_DEFAULT,
    };
    uart_driver_install(UART_PORT, BUF_SIZE * 2, BUF_SIZE * 2, 0, NULL, 0);
    uart_param_config(UART_PORT, &cfg);
    uart_set_pin(UART_PORT, UART_TX_PIN, UART_RX_PIN,
                 UART_PIN_NO_CHANGE, UART_PIN_NO_CHANGE);
}

// ---------------- Bridge tasks ----------------

// Mega -> Python: continuously read UART, forward to the connected socket (if any).
static void uart_to_socket_task(void *arg) {
    uint8_t data[BUF_SIZE];
    while (1) {
        int len = uart_read_bytes(UART_PORT, data, BUF_SIZE, pdMS_TO_TICKS(100));
        if (len > 0 && s_client_sock >= 0) {
            int sent = send(s_client_sock, data, len, 0);
            if (sent < 0) {
                ESP_LOGW(TAG, "send() failed, dropping client");
                close(s_client_sock);
                s_client_sock = -1;
            }
        }
    }
}

// Python -> Mega: accept one client at a time, forward everything it sends to UART.
static void socket_server_task(void *arg) {
    char rx_buffer[BUF_SIZE];

    int listen_sock = socket(AF_INET, SOCK_STREAM, IPPROTO_IP);
    if (listen_sock < 0) {
        ESP_LOGE(TAG, "Unable to create listen socket");
        vTaskDelete(NULL);
        return;
    }

    struct sockaddr_in server_addr = {
        .sin_family = AF_INET,
        .sin_addr.s_addr = htonl(INADDR_ANY),
        .sin_port = htons(BRIDGE_PORT),
    };
    bind(listen_sock, (struct sockaddr *)&server_addr, sizeof(server_addr));
    listen(listen_sock, 1);
    ESP_LOGI(TAG, "Listening for Python on port %d", BRIDGE_PORT);

    while (1) {
        struct sockaddr_in source_addr;
        socklen_t addr_len = sizeof(source_addr);
        int sock = accept(listen_sock, (struct sockaddr *)&source_addr, &addr_len);
        if (sock < 0) {
            ESP_LOGE(TAG, "accept() failed");
            continue;
        }
        ESP_LOGI(TAG, "Python connected.");
        s_client_sock = sock;

        while (1) {
            int len = recv(sock, rx_buffer, sizeof(rx_buffer), 0);
            if (len <= 0) {
                ESP_LOGI(TAG, "Python disconnected.");
                break;
            }
            uart_write_bytes(UART_PORT, rx_buffer, len);
        }

        close(sock);
        s_client_sock = -1;
    }
}

void app_main(void) {
    ESP_ERROR_CHECK(nvs_flash_init());
    wifi_init_sta();
    uart_init();

    xTaskCreate(uart_to_socket_task, "uart_to_socket_task", 4096, NULL, 10, NULL);
    xTaskCreate(socket_server_task, "socket_server_task", 4096, NULL, 10, NULL);
}
