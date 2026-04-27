FROM golang:1.26.1-bookworm AS build

WORKDIR /src

COPY go.mod go.sum ./
RUN go mod download

COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -trimpath -ldflags="-s -w" -o /out/gateway .

FROM scratch

COPY --from=build /out/gateway /gateway

EXPOSE 808

USER 65532:65532
ENTRYPOINT ["/gateway"]
