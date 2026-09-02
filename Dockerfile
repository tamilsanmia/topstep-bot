ARG FREQTRADE_IMAGE=freqtradeorg/freqtrade:latest
FROM ${FREQTRADE_IMAGE}

USER root

COPY projectx/ /tmp/projectx/
COPY scripts/install-projectx.sh /tmp/install-projectx.sh
COPY scripts/patch-frequi-trade-ws.sh /tmp/patch-frequi-trade-ws.sh

RUN chmod +x /tmp/install-projectx.sh /tmp/patch-frequi-trade-ws.sh \
    && FT_ROOT=/freqtrade /tmp/install-projectx.sh

COPY user_data/ /freqtrade/user_data/
COPY config.example.json /freqtrade/
COPY scripts/ /freqtrade/scripts/
COPY docker/entrypoint.sh /entrypoint.sh

RUN chmod +x /entrypoint.sh /freqtrade/scripts/*.sh /freqtrade/scripts/list_accounts.py 2>/dev/null || true \
    && chown -R ftuser:ftuser /freqtrade /entrypoint.sh

USER ftuser
WORKDIR /freqtrade

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8080/api/v1/ping || exit 1

ENTRYPOINT ["/entrypoint.sh"]
CMD ["trade"]
