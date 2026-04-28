FROM golang:1.26.1-bookworm AS base

WORKDIR /src
EXPOSE 808

COPY go.mod go.sum ./
RUN go mod download

FROM base AS dev

COPY . .
CMD ["go", "run", "."]

FROM base AS build

COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -trimpath -ldflags="-s -w" -o /out/gateway .

FROM scratch

COPY --from=build /out/gateway /gateway

USER 65532:65532
ENTRYPOINT ["/gateway"]
