CREATE TABLE `pages` (
  `id` int unsigned NOT NULL,
  `templates_id` int unsigned NOT NULL,
  `name` varchar(128) NOT NULL
);

CREATE TABLE `templates` (
  `id` int unsigned NOT NULL,
  `name` varchar(128) NOT NULL
);

CREATE TABLE `fields` (
  `id` int unsigned NOT NULL,
  `name` varchar(128) NOT NULL,
  `type` varchar(128) NOT NULL
);
