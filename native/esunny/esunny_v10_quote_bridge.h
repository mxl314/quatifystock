#pragma once

#if defined(_WIN32)
#define ESQ_EXPORT __declspec(dllexport)
#else
#define ESQ_EXPORT __attribute__((visibility("default")))
#endif

#ifdef __cplusplus
extern "C" {
#endif

typedef void (*esq_event_callback)(const char *event_type, const char *json_payload, void *user_data);

ESQ_EXPORT void *esq_create(esq_event_callback callback, void *user_data);
ESQ_EXPORT void esq_destroy(void *handle);
ESQ_EXPORT int esq_connect(void *handle, const char *ip, unsigned short port, const char *log_path);
ESQ_EXPORT int esq_subscribe(void *handle, const char *contract);
ESQ_EXPORT int esq_unsubscribe(void *handle, const char *contract);
ESQ_EXPORT int esq_query_contracts(void *handle);

#ifdef __cplusplus
}
#endif

